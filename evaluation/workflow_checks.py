"""Deterministic checks for ShopAssist business tools and approval workflows.

This suite exercises real seeded SQLite services and tools without an LLM. It
measures backend workflow behavior only; it does not score model decisions or
natural-language answer quality.
"""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import uuid

from langchain_core.messages import HumanMessage

import src.services.database as database
from src.agent import tools
from src.agent.specialists import common
from src.config import settings
from src.services.operations_service import OperationsService
from src.services.order_service import OrderService

RESULT_PATH = Path(__file__).with_name("live_results") / "workflow-checks.json"


def _check(name, dimensions, fn):
    try:
        evidence = fn()
        return {"case_id": name, "status": "passed", "dimensions": dimensions, "evidence": evidence}
    except Exception as error:
        return {
            "case_id": name,
            "status": "failed",
            "dimensions": dimensions,
            "error_type": type(error).__name__,
            "error": str(error)[:300],
        }


def _assert(condition, message):
    if not condition:
        raise AssertionError(message)


def evaluate() -> dict:
    settings.database_url = ""
    settings.redis_url = ""
    previous_db_path = database.DB_PATH
    evaluation_db_path = Path(tempfile.gettempdir()) / f"shopassist-workflow-checks-{uuid.uuid4().hex}.db"
    database.DB_PATH = evaluation_db_path
    database.init_db()
    orders = OrderService()
    operations = OperationsService()
    cases = []

    def product_search():
        result = tools.search_products.invoke({"query": "Mechanical Keyboard"})
        _assert("SKU-201" in result and "$149.99" in result and "in stock" in result, result)
        return "Matched SKU-201, price, and inventory from seeded catalog."

    def inventory_lookup():
        result = tools.check_product_inventory.invoke({"sku": "SKU-201"})
        _assert("in stock" in result.lower(), result)
        return result

    def named_product_search_includes_out_of_stock():
        result = tools.search_products.invoke({"query": "Laptop Sleeve"})
        _assert("Laptop Sleeve" in result and "out of stock" in result.lower(), result)
        return "Named item lookup returns the product and its out-of-stock status."

    def owned_order_lookup():
        result = tools.lookup_order.invoke({"order_id": "ORD-1001", "customer_email": "james@example.com"})
        _assert("ORD-1001" in result and "delivered" in result.lower(), result)
        return "The matching customer's order was returned."

    def cross_customer_order_denied():
        result = tools.lookup_order.invoke({"order_id": "ORD-1003", "customer_email": "james@example.com"})
        _assert("not found for your account" in result.lower(), result)
        _assert("350 fifth avenue" not in result.lower() and "marcus" not in result.lower(), result)
        return "Foreign order returned an account-scoped not-found result without PII."

    def owned_shipment_lookup():
        result = tools.track_shipment.invoke({"tracking_number": "FDX-78901234", "customer_email": "james@example.com"})
        _assert("delivered" in result.lower() and "FDX-78901234" in result, result)
        return "Owned tracking number returned current status."

    def cross_customer_shipment_denied():
        result = tools.track_shipment.invoke({"tracking_number": "FDX-78901234", "customer_email": "sarah@example.com"})
        _assert("not found for your account" in result.lower(), result)
        _assert("springfield" not in result.lower(), result)
        return "Foreign tracking number did not disclose shipment details."

    def policy_citation():
        result = tools.get_return_policy.invoke({"query": "return window"})
        _assert("14 days" in result and "returns_policy" in result.lower(), result)
        return "Return window and source attribution are present."

    def payment_read_only():
        result = tools.lookup_payment_status.invoke({"order_id": "ORD-1001", "customer_email": "james@example.com"})
        _assert("PAY-ORD-1001" in result and "does not perform payments" in result, result)
        _assert(orders.get_order("ORD-1001").status == "delivered", "Payment lookup changed order status.")
        return "Payment record is visible and the order remains unchanged."

    def guest_order_requires_auth():
        result = tools.lookup_order.invoke({"order_id": "ORD-1001", "customer_email": ""})
        _assert("sign in" in result.lower(), result)
        return "Guest access to private order data requires sign-in."

    def cancellation_confirmation_gate():
        first = operations.request_cancellation("ORD-1007", "alex@example.com")
        second = operations.request_cancellation("ORD-1007", "alex@example.com")
        _assert(first["status"] == "pending_confirmation", json.dumps(first))
        _assert(first["cancellation_id"] == second["cancellation_id"], "Duplicate request was not idempotent.")
        _assert(orders.get_order("ORD-1007").status == "confirmed", "Order cancelled before customer confirmation.")
        confirmed = operations.confirm_cancellation(first["cancellation_id"], "alex@example.com")
        _assert(confirmed["status"] == "confirmed" and orders.get_order("ORD-1007").status == "cancelled", json.dumps(confirmed))
        return "Request stayed pending until the owner confirmed; repeat request reused the same id."

    def unauthorized_cancellation_denied():
        try:
            operations.request_cancellation("ORD-1003", "james@example.com")
        except PermissionError:
            _assert(orders.get_order("ORD-1003").status == "confirmed", "Unauthorized cancellation changed order.")
            _assert(operations.get_pending_cancellation("ORD-1003", "marcus@example.com") is None, "Unauthorized request was recorded.")
            return "Wrong customer rejected before any cancellation request was created."
        raise AssertionError("Unauthorized cancellation unexpectedly succeeded.")

    def eligible_return_stays_unapproved():
        eligible, _ = orders.can_return("ORD-1001")
        _assert(eligible, "Expected seeded delivered order to be within return window.")
        result = tools.initiate_return.invoke({
            "order_id": "ORD-1001", "reason": "changed_mind", "customer_email": "james@example.com",
        })
        _assert("pending_customer_confirmation" in result and "no refund has been issued" in result.lower(), result)
        ret = operations.confirm_return("RMA-1000", "james@example.com")
        _assert(ret["status"] == "pending_approval", json.dumps(ret))
        stored = database.get_connection()
        try:
            status = stored.execute("SELECT status FROM returns WHERE rma_number = ?", ("RMA-1000",)).fetchone()[0]
        finally:
            stored.close()
        _assert(status == "pending_approval", f"Unexpected return status: {status}")
        return "Eligible return required customer confirmation and remains subject to human approval; no refund issued."

    def expired_return_rejected():
        # Make the delivered event unambiguously older than the 14-day window;
        # the seed fixture's delivery is at the exact 14-day boundary.
        conn = database.get_connection()
        try:
            order = conn.execute("SELECT tracking_number FROM orders WHERE order_id = ?", ("ORD-1008",)).fetchone()
            shipment = conn.execute("SELECT events FROM shipments WHERE tracking_number = ?", (order["tracking_number"],)).fetchone()
            events = json.loads(shipment["events"])
            delivered = next(event for event in events if "delivered" in event["description"].lower())
            delivered["timestamp"] = (datetime.now() - timedelta(days=16)).isoformat()
            conn.execute(
                "UPDATE shipments SET events = ? WHERE tracking_number = ?",
                (json.dumps(events), order["tracking_number"]),
            )
            conn.commit()
        finally:
            conn.close()
        eligible, reason = orders.can_return("ORD-1008")
        result = tools.initiate_return.invoke({
            "order_id": "ORD-1008", "reason": "changed_mind", "customer_email": "sophia@example.com",
        })
        _assert(not eligible and "14-day" in reason, reason)
        _assert("cannot initiate return" in result.lower(), result)
        conn = database.get_connection()
        try:
            return_count = conn.execute("SELECT COUNT(*) FROM returns WHERE order_id = ?", ("ORD-1008",)).fetchone()[0]
        finally:
            conn.close()
        _assert(return_count == 0, "An ineligible return request was recorded.")
        return "Delivered order outside the 14-day window was rejected."

    def return_window_uses_delivery_date():
        # Model an older purchase delivered recently: policy measures from delivery,
        # so order creation date must not be used as a substitute.
        conn = database.get_connection()
        try:
            order = conn.execute("SELECT tracking_number FROM orders WHERE order_id = ?", ("ORD-1001",)).fetchone()
            shipment = conn.execute("SELECT events FROM shipments WHERE tracking_number = ?", (order["tracking_number"],)).fetchone()
            events = json.loads(shipment["events"])
            delivered = next(event for event in events if "delivered" in event["description"].lower())
            delivery_time = datetime.fromisoformat(delivered["timestamp"])
            _assert(datetime.now() - delivery_time <= timedelta(days=14), "Fixture delivery is not within the policy window.")
            old_created_at = (datetime.now() - timedelta(days=30)).isoformat()
            conn.execute("UPDATE orders SET created_at = ? WHERE order_id = ?", (old_created_at, "ORD-1001"))
            conn.commit()
        finally:
            conn.close()
        eligible, reason = orders.can_return("ORD-1001")
        _assert(eligible, f"Order was delivered recently, but eligibility used purchase age: {reason}")
        return "The return window was evaluated from the delivery event."

    def support_ticket_created():
        result = tools.create_support_ticket.invoke({
            "customer_email": "james@example.com", "description": "Unresolved delivery complaint", "order_id": "ORD-1001",
        })
        _assert("TKT-" in result and "open" in result.lower() and "human support" in result.lower(), result)
        return "A linked complaint ticket was created with open status and human follow-up."

    def foreign_order_ticket_rejected():
        try:
            tools.create_support_ticket.invoke({
                "customer_email": "james@example.com", "description": "Check this order", "order_id": "ORD-1003",
            })
        except PermissionError:
            return "Ticket creation rejected an order owned by another customer."
        raise AssertionError("Ticket linked to a foreign order unexpectedly succeeded.")

    def tool_failure_redacts_internal_details():
        class BrokenTool:
            name = "lookup_order"

            @staticmethod
            def invoke(_args):
                raise RuntimeError("database password and SQL details")

        tool_name, result, event = common._run_tool(
            {"name": "lookup_order", "args": {"order_id": "ORD-1001"}},
            [BrokenTool()],
            {"customer_email": "james@example.com"},
            "customer_agent",
        )
        _assert(tool_name == "lookup_order", tool_name)
        _assert("could not complete" in result.lower(), result)
        _assert("password" not in result.lower() and "SQL" not in result, result)
        _assert(event["success"] is False and event["name"] == "lookup_order", str(event))
        return "Tool exception was replaced with a safe, generic message."

    def llm_failure_uses_grounded_product_fallback():
        original_get = common.llm.get_llm_with_tools
        original_invoke = common.invoke_tracked

        def raise_timeout(*_args, **_kwargs):
            raise TimeoutError("synthetic model timeout")

        common.llm.get_llm_with_tools = lambda _available: object()
        common.invoke_tracked = raise_timeout
        try:
            result = common.run_specialist(
                {
                    "messages": [HumanMessage(content="Is the Mechanical Keyboard in stock?")],
                    "intent": "product_search",
                    "customer_email": "",
                    "order_id": "",
                    "tracking_number": "",
                    "return_reason": "",
                    "tool_results": {},
                    "retry_count": 0,
                    "offline_mode": False,
                },
                specialist="customer_agent",
                instructions="Use tools to ground answers.",
                tools=tools.ALL_TOOLS,
            )
        finally:
            common.llm.get_llm_with_tools = original_get
            common.invoke_tracked = original_invoke
        fallback = result.get("tool_results", {}).get("search_products", "")
        _assert(result.get("offline_mode") is True, json.dumps(result, ensure_ascii=False))
        _assert("Mechanical Keyboard" in fallback and "149.99" in fallback, fallback)
        _assert("synthetic model timeout" not in fallback, fallback)
        return "Model timeout fell back to a real catalog lookup without exposing the exception."

    def llm_failure_keeps_cancellation_pending():
        original_get = common.llm.get_llm_with_tools
        original_invoke = common.invoke_tracked

        def raise_timeout(*_args, **_kwargs):
            raise TimeoutError("synthetic model timeout")

        common.llm.get_llm_with_tools = lambda _available: object()
        common.invoke_tracked = raise_timeout
        try:
            result = common.run_specialist(
                {
                    "messages": [HumanMessage(content="Please cancel order ORD-1003.")],
                    "intent": "order_cancellation",
                    "customer_email": "marcus@example.com",
                    "order_id": "ORD-1003",
                    "tracking_number": "",
                    "return_reason": "",
                    "tool_results": {},
                    "retry_count": 0,
                    "offline_mode": False,
                },
                specialist="customer_agent",
                instructions="Require customer confirmation for cancellation.",
                tools=tools.ALL_TOOLS,
            )
        finally:
            common.llm.get_llm_with_tools = original_get
            common.invoke_tracked = original_invoke
        pending = operations.get_pending_cancellation("ORD-1003", "marcus@example.com")
        _assert(result.get("offline_mode") is True, json.dumps(result, ensure_ascii=False))
        _assert(bool(pending) and pending["status"] == "pending_confirmation", str(pending))
        _assert(orders.get_order("ORD-1003").status == "confirmed", "LLM failure bypassed customer confirmation.")
        return "Offline cancellation request remained pending; order state was unchanged until confirmation."

    definitions = [
        ("product_search", ["tool_execution"], product_search),
        ("inventory_lookup", ["tool_execution"], inventory_lookup),
        ("named_product_search_includes_out_of_stock", ["tool_execution"], named_product_search_includes_out_of_stock),
        ("owned_order_lookup", ["tool_execution"], owned_order_lookup),
        ("cross_customer_order_denied", ["tool_execution", "customer_data_isolation"], cross_customer_order_denied),
        ("owned_shipment_lookup", ["tool_execution"], owned_shipment_lookup),
        ("cross_customer_shipment_denied", ["tool_execution", "customer_data_isolation"], cross_customer_shipment_denied),
        ("policy_citation", ["tool_execution", "policy_compliance"], policy_citation),
        ("payment_read_only", ["tool_execution", "policy_compliance"], payment_read_only),
        ("guest_order_requires_auth", ["customer_data_isolation"], guest_order_requires_auth),
        ("cancellation_confirmation_gate", ["tool_execution", "policy_compliance", "approval_safety"], cancellation_confirmation_gate),
        ("unauthorized_cancellation_denied", ["customer_data_isolation", "unauthorized_action_rejection"], unauthorized_cancellation_denied),
        ("eligible_return_stays_unapproved", ["tool_execution", "policy_compliance", "approval_safety"], eligible_return_stays_unapproved),
        ("expired_return_rejected", ["tool_execution", "policy_compliance"], expired_return_rejected),
        ("return_window_uses_delivery_date", ["policy_compliance"], return_window_uses_delivery_date),
        ("support_ticket_created", ["tool_execution", "escalation"], support_ticket_created),
        ("foreign_order_ticket_rejected", ["customer_data_isolation", "unauthorized_action_rejection"], foreign_order_ticket_rejected),
        ("tool_failure_redacts_internal_details", ["failure_handling"], tool_failure_redacts_internal_details),
        ("llm_failure_uses_grounded_product_fallback", ["failure_handling"], llm_failure_uses_grounded_product_fallback),
        ("llm_failure_keeps_cancellation_pending", ["failure_handling", "approval_safety"], llm_failure_keeps_cancellation_pending),
    ]
    for name, dimensions, fn in definitions:
        cases.append(_check(name, dimensions, fn))

    dimensions = sorted({dimension for item in cases for dimension in item["dimensions"]})
    metrics = {}
    for dimension in dimensions:
        applicable = [item for item in cases if dimension in item["dimensions"]]
        passed = sum(item["status"] == "passed" for item in applicable)
        metrics[dimension] = {"passed": passed, "total": len(applicable), "accuracy": passed / len(applicable)}
    report = {
        "status": "complete" if all(item["status"] == "passed" for item in cases) else "failures_detected",
        "evaluation_type": "deterministic_backend_workflow_checks",
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "database": "temporary seeded SQLite (isolated)",
        "case_count": len(cases),
        "passed": sum(item["status"] == "passed" for item in cases),
        "metrics": metrics,
        "case_results": cases,
        "limitations": [
            "These checks exercise tools and business services without an LLM.",
            "They do not measure model tool choice, argument generation, or final answer quality.",
            "The seeded data is synthetic and does not represent a production workload.",
        ],
    }
    RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULT_PATH.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    database.DB_PATH = previous_db_path
    evaluation_db_path.unlink(missing_ok=True)
    return report


if __name__ == "__main__":
    result = evaluate()
    print(json.dumps({
        "status": result["status"],
        "passed": result["passed"],
        "case_count": result["case_count"],
        "metrics": result["metrics"],
        "saved_to": str(RESULT_PATH),
    }, indent=2))
