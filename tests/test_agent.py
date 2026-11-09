"""
Unit & Integration tests for the E-Commerce Support Agent.
"""
import json
import time
import uuid
import tempfile
from datetime import datetime

import pytest
from src.services.database import get_connection, init_db
import src.services.database as database
from src.config import settings


@pytest.fixture(scope="module", autouse=True)
def _setup_database():
    """Use isolated SQLite fixtures even when a developer has PostgreSQL configured."""
    previous_url, previous_redis, previous_path = settings.database_url, settings.redis_url, database.DB_PATH
    with tempfile.TemporaryDirectory(prefix="shopassist-agent-tests-") as temp_dir:
        settings.database_url = ""
        settings.redis_url = ""
        database.DB_PATH = __import__("pathlib").Path(temp_dir) / "agent-tests.sqlite3"
        init_db()
        yield
    settings.database_url, settings.redis_url, database.DB_PATH = previous_url, previous_redis, previous_path


@pytest.fixture
def workflow_orders():
    """Create isolated orders for state-changing workflow tests."""
    suffix = uuid.uuid4().hex[:8].upper()
    orders = [
        (f"TST-C-{suffix}", "confirmed"),
        (f"TST-R-{suffix}", "delivered"),
    ]
    conn = get_connection()
    try:
        for order_id, status in orders:
            conn.execute(
                """INSERT INTO orders
                   (order_id, customer_name, email, items, status, total,
                    created_at, shipping_address, tracking_number)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    order_id,
                    "Test Customer",
                    f"{order_id.lower()}@example.com",
                    json.dumps([]),
                    status,
                    25.0,
                    datetime.now().isoformat(),
                    "Test Address",
                    None,
                ),
            )
        conn.commit()
    finally:
        conn.close()
    try:
        yield orders
    finally:
        conn = get_connection()
        try:
            for order_id, _ in orders:
                email = f"{order_id.lower()}@example.com"
                conn.execute("DELETE FROM conversation_messages WHERE customer_email = ?", (email,))
                conn.execute("DELETE FROM auth_sessions WHERE email = ?", (email,))
                conn.execute("DELETE FROM customers WHERE email = ?", (email,))
                conn.execute("DELETE FROM payments WHERE order_id = ?", (order_id,))
                conn.execute("DELETE FROM returns WHERE order_id = ?", (order_id,))
                conn.execute(
                    "DELETE FROM cancellation_requests WHERE order_id = ?", (order_id,)
                )
                conn.execute("DELETE FROM support_tickets WHERE order_id = ?", (order_id,))
                conn.execute("DELETE FROM orders WHERE order_id = ?", (order_id,))
            conn.commit()
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# Service tests (no LLM needed)
# ---------------------------------------------------------------------------


class TestOrderService:
    def test_get_existing_order(self):
        from src.services.order_service import OrderService

        svc = OrderService()
        order = svc.get_order("ORD-1001")
        assert order is not None
        assert order.customer_name == "James Wilson"
        assert order.status == "delivered"
        assert len(order.items) == 2

    def test_get_missing_order(self):
        from src.services.order_service import OrderService

        svc = OrderService()
        order = svc.get_order("ORD-9999")
        assert order is None

    def test_get_orders_by_email(self):
        from src.services.order_service import OrderService

        svc = OrderService()
        orders = svc.get_orders_by_email("james@example.com")
        assert len(orders) >= 1
        assert any(o.order_id == "ORD-1001" for o in orders)

    def test_get_orders_by_email_multiple(self):
        from src.services.order_service import OrderService

        svc = OrderService()
        orders = svc.get_orders_by_email("james@example.com")
        assert len(orders) == 2

    def test_search_orders_by_name(self):
        from src.services.order_service import OrderService

        svc = OrderService()
        results = svc.search_orders("James")
        assert len(results) >= 2

    def test_search_orders_by_product(self):
        from src.services.order_service import OrderService

        svc = OrderService()
        results = svc.search_orders("Headphones")
        assert len(results) >= 1

    def test_get_all_orders(self):
        from src.services.order_service import OrderService

        svc = OrderService()
        orders = svc.get_all_orders()
        order_ids = {order.order_id for order in orders}
        assert {f"ORD-{number}" for number in range(1001, 1013)} <= order_ids

    def test_can_return_delivered_order(self):
        from src.services.order_service import OrderService

        svc = OrderService()
        can, msg = svc.can_return("ORD-1001")
        assert can is True

    def test_cannot_return_cancelled_order(self):
        from src.services.order_service import OrderService

        svc = OrderService()
        can, msg = svc.can_return("ORD-1004")
        assert can is False
        assert "cancel" in msg.lower()

    def test_cannot_return_unshipped_order(self):
        from src.services.order_service import OrderService

        svc = OrderService()
        can, msg = svc.can_return("ORD-1003")
        assert can is False

    def test_cannot_return_expired_order(self):
        from src.services.order_service import OrderService

        svc = OrderService()
        can, msg = svc.can_return("ORD-1008")
        assert can is False
        assert "14" in msg


class TestShippingService:
    def test_track_existing(self):
        from src.services.shipping_service import ShippingService

        svc = ShippingService()
        shipment = svc.track("FDX-78901234")
        assert shipment is not None
        assert shipment.carrier == "FedEx"
        assert shipment.status == "delivered"

    def test_track_missing(self):
        from src.services.shipping_service import ShippingService

        svc = ShippingService()
        shipment = svc.track("XXX-00000000")
        assert shipment is None

    def test_readable_status(self):
        from src.services.shipping_service import ShippingService

        svc = ShippingService()
        status = svc.get_readable_status("FDX-78901234")
        assert "delivered" in status.lower()


class TestProductAndPaymentServices:
    def test_search_products_and_inventory(self):
        from src.services.product_service import ProductService

        service = ProductService()
        results = service.search("keyboard")
        assert len(results) == 1
        assert results[0].sku == "SKU-201"
        assert results[0].inventory == 7

        out_of_stock = service.get_by_sku("SKU-1101")
        assert out_of_stock is not None
        assert out_of_stock.inventory == 0
        available = service.search(category="Computers", in_stock=True)
        assert available
        assert all(product.category == "Computers" for product in available)
        assert all(product.inventory > 0 for product in available)
        assert "Computers" in service.get_categories()

    def test_payment_lookup_is_scoped_to_customer_order(self):
        from src.services.payment_service import PaymentService

        service = PaymentService()
        payment = service.get_for_order("ORD-1002", "sarah@example.com")
        assert payment is not None
        assert payment.status == "paid"
        assert service.get_for_order("ORD-1002", "wrong@example.com") is None


class TestReturnsService:
    def test_create_return(self, workflow_orders):
        from src.services.returns_service import ReturnsService

        order_id, _ = workflow_orders[1]
        svc = ReturnsService()
        ret = svc.create_return(order_id, "defective", 25.0)
        assert ret.rma_number.startswith("RMA-")
        assert ret.status == "pending_customer_confirmation"
        assert ret.refund_amount == 25.0

    def test_get_policy(self):
        from src.services.returns_service import ReturnsService

        svc = ReturnsService()
        policy = svc.get_policy()
        assert "14 days" in policy


class TestOperations:
    def test_confirmed_cancellation_updates_order(self, workflow_orders):
        from src.services.operations_service import OperationsService
        from src.services.order_service import OrderService

        order_id, _ = workflow_orders[0]
        email = f"{order_id.lower()}@example.com"
        operations = OperationsService()

        request = operations.request_cancellation(order_id, email)
        assert request["status"] == "pending_confirmation"
        assert OrderService().get_order(order_id).status == "confirmed"

        confirmed = operations.confirm_cancellation(request["cancellation_id"], email)
        assert confirmed["status"] == "confirmed"
        assert OrderService().get_order(order_id).status == "cancelled"
        assert operations.confirm_cancellation(request["cancellation_id"], email)["status"] == "confirmed"

    def test_cancellation_requires_matching_email(self, workflow_orders):
        from src.services.operations_service import OperationsService

        order_id, _ = workflow_orders[0]
        with pytest.raises(PermissionError):
            OperationsService().request_cancellation(order_id, "wrong@example.com")

    def test_return_requires_customer_confirmation_and_admin_approval(self, workflow_orders):
        from src.services.operations_service import OperationsService
        from src.services.returns_service import ReturnsService

        order_id, _ = workflow_orders[1]
        email = f"{order_id.lower()}@example.com"
        ret = ReturnsService().create_return(order_id, "defective", 25.0)
        operations = OperationsService()

        with pytest.raises(PermissionError):
            operations.confirm_return(ret.rma_number, "wrong@example.com")
        with pytest.raises(ValueError):
            operations.approve_return(ret.rma_number)

        confirmed = operations.confirm_return(ret.rma_number, email)
        assert confirmed["status"] == "pending_approval"
        approved = operations.approve_return(ret.rma_number)
        assert approved["status"] == "approved"

    def test_creates_support_ticket(self, workflow_orders):
        from src.services.operations_service import OperationsService

        order_id, _ = workflow_orders[0]
        email = f"{order_id.lower()}@example.com"
        ticket = OperationsService().create_support_ticket(
            f" {email} ", "Please have a person contact me.", order_id
        )
        assert ticket["ticket_id"].startswith("TKT-")
        assert ticket["customer_email"] == email
        assert ticket["status"] == "open"

    def test_workflow_api_requires_customer_and_admin_steps(
        self, workflow_orders, monkeypatch
    ):
        from fastapi.testclient import TestClient

        from src.config import settings
        from src.main import app
        from src.services import auth_service as auth_module

        cancellation_order, return_order = workflow_orders
        cancellation_id, _ = cancellation_order
        return_id, _ = return_order
        cancellation_email = f"{cancellation_id.lower()}@example.com"
        return_email = f"{return_id.lower()}@example.com"
        monkeypatch.setattr(settings, "admin_api_key", "test-admin-key")
        monkeypatch.setattr(
            settings, "auth_secret_key", "test-auth-secret-key-that-is-long-enough"
        )
        sent_codes = []
        monkeypatch.setattr(
            auth_module,
            "_send_verification_email",
            lambda email, code: sent_codes.append((email, code)),
        )

        with TestClient(app) as client:
            assert client.post("/api/v1/chat", json={"message": "hello"}).status_code == 401
            assert client.post(
                "/api/v1/orders/cancellation-requests",
                json={"order_id": cancellation_id},
            ).status_code == 401
            assert client.get("/api/v1/orders/mine").status_code == 401
            public_products = client.get("/api/v1/products")
            assert public_products.status_code == 200
            assert public_products.json()

            def register_and_login(email):
                response = client.post(
                    "/api/v1/auth/register",
                    json={
                        "email": email,
                        "full_name": "Test Customer",
                        "password": "a-secure-test-password",
                    },
                )
                assert response.status_code == 202
                code_email, code = sent_codes[-1]
                assert code_email == email
                assert client.post(
                    "/api/v1/auth/verify-email",
                    json={"email": email, "code": code},
                ).status_code == 200
                login = client.post(
                    "/api/v1/auth/login",
                    json={"email": email, "password": "a-secure-test-password"},
                )
                assert login.status_code == 200
                return login.json()["access_token"]

            cancellation_token = register_and_login(cancellation_email)
            cancellation_headers = {
                "Authorization": f"Bearer {cancellation_token}"
            }
            assert client.post(
                "/api/v1/auth/login",
                json={"email": cancellation_email, "password": "wrong-password"},
            ).status_code == 401

            return_token = register_and_login(return_email)
            return_headers = {"Authorization": f"Bearer {return_token}"}
            catalog_response = client.get(
                "/api/v1/products",
                params={"query": "keyboard", "in_stock": "true"},
                headers=return_headers,
            )
            assert catalog_response.status_code == 200
            assert [item["sku"] for item in catalog_response.json()] == ["SKU-201"]
            categories_response = client.get(
                "/api/v1/products/categories", headers=return_headers
            )
            assert "Computers" in categories_response.json()["categories"]

            cancellation_orders = client.get(
                "/api/v1/orders/mine", headers=cancellation_headers
            )
            return_orders = client.get("/api/v1/orders/mine", headers=return_headers)
            assert [item["order_id"] for item in cancellation_orders.json()] == [
                cancellation_id
            ]
            assert [item["order_id"] for item in return_orders.json()] == [return_id]
            assert "shipping_address" not in return_orders.json()[0]
            assert "email" not in return_orders.json()[0]

            response = client.post(
                "/api/v1/orders/cancellation-requests",
                json={"order_id": cancellation_id},
                headers=cancellation_headers,
            )
            assert response.status_code == 200
            cancellation = response.json()
            assert cancellation["status"] == "pending_confirmation"

            # A different verified customer cannot use their token on this order.
            response = client.post(
                "/api/v1/orders/cancellation-requests",
                json={"order_id": cancellation_id},
                headers=return_headers,
            )
            assert response.status_code == 403

            response = client.post(
                f"/api/v1/cancellation-requests/{cancellation['cancellation_id']}/confirm",
                headers=cancellation_headers,
            )
            assert response.status_code == 200
            assert response.json()["status"] == "confirmed"

            response = client.post(
                "/api/v1/returns/requests",
                json={
                    "order_id": return_id,
                    "reason": "defective",
                },
                headers=return_headers,
            )
            assert response.status_code == 200
            return_request = response.json()
            assert return_request["status"] == "pending_customer_confirmation"

            response = client.post(
                f"/api/v1/returns/{return_request['rma_number']}/confirm",
                headers=return_headers,
            )
            assert response.status_code == 200
            assert response.json()["status"] == "pending_approval"

            approve_url = f"/api/v1/admin/returns/{return_request['rma_number']}/approve"
            assert client.post(approve_url, headers={"X-Admin-Key": "wrong"}).status_code == 401
            response = client.post(
                approve_url, headers={"X-Admin-Key": "test-admin-key"}
            )
            assert response.status_code == 200
            assert response.json()["status"] == "approved"
            assert "no payment was transferred" in response.json()["message"].lower()

            response = client.post(
                "/api/v1/support/tickets",
                json={
                    "description": "Please escalate this delivery complaint.",
                    "order_id": return_id,
                },
                headers=return_headers,
            )
            assert response.status_code == 200
            assert response.json()["status"] == "open"

            assert client.get("/api/v1/auth/me", headers=return_headers).status_code == 200
            assert client.post("/api/v1/auth/logout", headers=return_headers).status_code == 200
            assert client.get("/api/v1/auth/me", headers=return_headers).status_code == 401


# ---------------------------------------------------------------------------
# Agent tool tests (no LLM needed)
# ---------------------------------------------------------------------------


class TestAgentTools:
    def test_lookup_order(self):
        from src.agent.tools import lookup_order

        result = lookup_order.invoke(
            {"order_id": "ORD-1001", "customer_email": "james@example.com"}
        )
        assert "James Wilson" in result
        assert "delivered" in result
        assert "105.97" in result

    def test_lookup_missing_order(self):
        from src.agent.tools import lookup_order

        result = lookup_order.invoke(
            {"order_id": "ORD-XXXX", "customer_email": "james@example.com"}
        )
        assert "not found" in result.lower()

    def test_agent_tool_arguments_cannot_override_authenticated_email(self, monkeypatch):
        from langchain_core.messages import AIMessage, HumanMessage

        from src.agent import llm
        from src.agent.specialists.order_agent import order_agent_node

        class FakeToolLLM:
            def invoke(self, messages):
                return AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "lookup_orders_by_email",
                            "args": {"email": "james@example.com"},
                            "id": "test-call",
                            "type": "tool_call",
                        }
                    ],
                )

        monkeypatch.setattr(
            llm, "get_llm_with_tools", lambda tools=None: FakeToolLLM()
        )
        result = order_agent_node(
            {
                "intent": "order_status",
                "messages": [HumanMessage(content="Show me my orders")],
                "specialist": "order_agent",
                "customer_email": "sarah@example.com",
                "retry_count": 0,
            }
        )
        tool_result = result["tool_results"]["lookup_orders_by_email"]
        assert "ORD-1002" in tool_result
        assert "ORD-1001" not in tool_result

    def test_track_shipment(self):
        from src.agent.tools import track_shipment

        result = track_shipment.invoke(
            {
                "tracking_number": "UPS-45678901",
                "customer_email": "sarah@example.com",
            }
        )
        assert "UPS" in result
        assert "IN_TRANSIT" in result

    def test_get_return_policy(self):
        from src.agent.tools import get_return_policy

        result = get_return_policy.invoke({})
        assert "14 days" in result

    def test_check_return_eligibility(self):
        from src.agent.tools import check_return_eligibility

        result = check_return_eligibility.invoke(
            {"order_id": "ORD-1001", "customer_email": "james@example.com"}
        )
        assert "✅" in result

    def test_cancellation_tool_only_creates_pending_request(self, workflow_orders):
        from src.agent.tools import request_order_cancellation
        from src.services.order_service import OrderService

        order_id, _ = workflow_orders[0]
        email = f"{order_id.lower()}@example.com"
        result = request_order_cancellation.invoke(
            {"order_id": order_id, "customer_email": email}
        )
        assert "has not been cancelled" in result.lower()
        assert "pending_confirmation" in result
        assert OrderService().get_order(order_id).status == "confirmed"

    def test_return_tool_requires_customer_email_before_creating_request(
        self, workflow_orders
    ):
        from src.agent.tools import initiate_return
        from src.services.returns_service import ReturnsService

        order_id, _ = workflow_orders[1]
        result = initiate_return.invoke(
            {"order_id": order_id, "reason": "defective"}
        )
        assert "provide the order ID and the email" in result
        assert ReturnsService().get_return(order_id) is None

    def test_product_and_payment_specialist_tools(self):
        from src.agent.tools import lookup_payment_status, search_products

        products = search_products.invoke({"query": "keyboard"})
        assert "Mechanical Keyboard" in products
        assert "7 in stock" in products

        payment = lookup_payment_status.invoke(
            {"order_id": "ORD-1002", "customer_email": "sarah@example.com"}
        )
        assert "PAID" in payment
        assert "does not perform payments" in payment


# ---------------------------------------------------------------------------
# Graph structure test (no LLM needed)
# ---------------------------------------------------------------------------


class TestGraph:
    def test_graph_builds(self):
        from src.agent.graph import build_graph

        graph = build_graph()
        assert graph is not None

    def test_graph_has_nodes(self):
        from src.agent.graph import build_graph

        graph = build_graph()
        nodes = graph.get_graph().nodes
        assert "supervisor" in nodes
        assert "agent" in nodes
        assert "response" in nodes
        assert not {
            "order_agent",
            "returns_agent",
            "product_agent",
            "payment_agent",
            "support_agent",
        }.intersection(nodes)

    def test_should_use_tools_logic(self):
        from src.agent.graph import route_from_supervisor

        assert route_from_supervisor({"intent": "order_status"}) == "agent"
        assert route_from_supervisor({"intent": "shipping_tracking"}) == "agent"
        assert route_from_supervisor({"intent": "order_cancellation"}) == "agent"
        assert route_from_supervisor({"intent": "return_request"}) == "agent"
        assert route_from_supervisor({"intent": "general"}) == "response"
        assert route_from_supervisor({"intent": "return_policy"}) == "agent"
        assert route_from_supervisor({"intent": "product_search"}) == "agent"
        assert route_from_supervisor({"intent": "payment_status"}) == "agent"
        assert route_from_supervisor({"intent": "support_escalation"}) == "agent"

    def test_shared_agent_has_only_declared_domain_tools(self):
        from src.agent.tools import ALL_TOOLS

        tool_names = {tool.name for tool in ALL_TOOLS}
        assert {
            "lookup_order",
            "track_shipment",
            "get_return_policy",
            "initiate_return",
            "search_products",
            "lookup_payment_status",
            "create_support_ticket",
        } <= tool_names
        assert len(tool_names) == len(ALL_TOOLS)

    def test_tracking_number_routes_to_shipping_not_order_status(self):
        from langchain_core.messages import HumanMessage

        from src.agent.graph import route_from_supervisor
        from src.agent.supervisor import supervisor_node

        result = supervisor_node({
            "messages": [HumanMessage(content="Where is package FDX-78901234?")],
            "customer_email": "customer@example.com",
        })

        assert result["intent"] == "shipping_tracking"
        assert result["tracking_number"] == "FDX-78901234"
        assert route_from_supervisor(result) == "agent"

    def test_order_ordinal_followup_uses_previous_order_list_and_authenticated_lookup(
        self, monkeypatch
    ):
        from langchain_core.messages import AIMessage, HumanMessage

        from src.agent import llm
        from src.agent.graph import agent_graph

        monkeypatch.setattr(
            llm,
            "get_llm_with_tools",
            lambda tools: (_ for _ in ()).throw(RuntimeError("model unavailable")),
        )
        result = agent_graph.invoke({
            "messages": [
                AIMessage(content=(
                    "I checked your orders: **ORD-1002** — confirmed; tracking not assigned yet; "
                    "**ORD-1001** — delivered. Which order number would you like me to check further?"
                )),
                HumanMessage(content="the first one"),
            ],
            "intent": "",
            "specialist": "",
            "order_id": "",
            "tracking_number": "",
            "customer_email": "sarah@example.com",
            "tool_results": {},
            "final_response": "",
            "retry_count": 0,
            "error_message": "",
        })

        assert result["intent"] == "order_status"
        assert result["order_id"] == "ORD-1002"
        assert "ORD-1002" in result["tool_results"]["lookup_order"]
        assert "ORD-1001" not in result["tool_results"]["lookup_order"]
        assert "ORD-1002" in result["final_response"]

    def test_graph_runs_supervisor_to_shared_customer_agent(self, monkeypatch):
        from langchain_core.messages import AIMessage, HumanMessage

        from src.agent import llm
        from src.agent.graph import agent_graph

        class FakeLLM:
            def invoke(self, messages):
                prompt = messages[0].content
                if "triage and entity-resolution" in prompt:
                    return AIMessage(
                        content=json.dumps(
                            {
                                "intent": "product_search",
                                "order_id": "",
                                "tracking_number": "",
                                "customer_email": "",
                            }
                        )
                    )
                return AIMessage(content="I found the product in the catalog.")

        class FakeProductAgent:
            def __init__(self):
                self.turns = 0

            def invoke(self, messages):
                self.turns += 1
                tool_messages = [
                    message for message in messages
                    if getattr(message, "type", "") == "tool"
                ]
                if len(tool_messages) == 1:
                    assert "Mechanical Keyboard" in str(tool_messages[0].content)
                    return AIMessage(
                        content="",
                        tool_calls=[{
                            "name": "check_product_inventory",
                            "args": {"sku": "SKU-201"},
                            "id": "inventory-check",
                            "type": "tool_call",
                        }],
                    )
                if len(tool_messages) == 2:
                    assert "7 in stock" in str(tool_messages[1].content)
                    return AIMessage(
                        content="Yes. The Mechanical Keyboard is $149.99 and 7 are in stock. "
                        "It is a tenkeyless model with tactile switches."
                    )
                return AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "search_products",
                            "args": {"query": "keyboard"},
                            "id": "product-search",
                            "type": "tool_call",
                        }
                    ],
                )

        monkeypatch.setattr(llm, "get_llm", lambda: FakeLLM())
        product_agent = FakeProductAgent()
        monkeypatch.setattr(
            llm, "get_llm_with_tools", lambda tools: product_agent
        )
        result = agent_graph.invoke(
            {
                "messages": [HumanMessage(content="Do you have keyboards in stock?")],
                "intent": "",
                "specialist": "",
                "order_id": "",
                "tracking_number": "",
                "customer_email": "",
                "tool_results": {},
                "final_response": "",
                "retry_count": 0,
                "error_message": "",
            }
        )
        assert result["specialist"] == "customer_agent"
        assert "Mechanical Keyboard" in result["tool_results"]["search_products"]
        assert "7 in stock" in result["tool_results"]["check_product_inventory"]
        assert "Mechanical Keyboard" in result["final_response"]
        assert "7" in result["final_response"]
        assert "in stock" in result["final_response"]
        assert "Yes." in result["final_response"]
        assert result["retry_count"] == 1
        assert product_agent.turns == 3

    def test_graph_uses_grounded_product_fallback_when_llm_is_unavailable(self, monkeypatch):
        from langchain_core.messages import HumanMessage

        from src.agent import llm
        from src.agent.graph import agent_graph

        def unavailable_model():
            raise RuntimeError("model endpoint is unreachable")

        monkeypatch.setattr(llm, "get_llm", unavailable_model)
        result = agent_graph.invoke({
            "messages": [HumanMessage(content="Do you have keyboards in stock?")],
            "intent": "",
            "specialist": "",
            "order_id": "",
            "tracking_number": "",
            "customer_email": "sarah@example.com",
            "tool_results": {},
            "final_response": "",
            "retry_count": 0,
            "error_message": "",
        })

        assert result["intent"] == "product_search"
        assert "Mechanical Keyboard" in result["final_response"]
        assert "7 in stock" in result["final_response"]
        assert not result["error_message"]

    def test_offline_recommendation_does_not_present_a_sleeve_as_a_laptop(self, monkeypatch):
        from langchain_core.messages import HumanMessage

        from src.agent import llm
        from src.agent.graph import agent_graph

        monkeypatch.setattr(
            llm, "get_llm", lambda: (_ for _ in ()).throw(RuntimeError("offline"))
        )
        result = agent_graph.invoke({
            "messages": [HumanMessage(content="Recommend a laptop for everyday work.")],
            "intent": "",
            "specialist": "",
            "order_id": "",
            "tracking_number": "",
            "customer_email": "qa@example.test",
            "tool_results": {},
            "final_response": "",
            "retry_count": 0,
            "error_message": "",
        })

        assert "couldn't find an in-stock laptop" in result["final_response"]
        assert "Laptop Sleeve" not in result["final_response"]

    def test_unknown_question_gets_scope_reply_when_llm_is_unavailable(self, monkeypatch):
        from langchain_core.messages import HumanMessage

        from src.agent import llm
        from src.agent.graph import agent_graph

        monkeypatch.setattr(
            llm, "get_llm", lambda: (_ for _ in ()).throw(RuntimeError("offline"))
        )
        result = agent_graph.invoke({
            "messages": [HumanMessage(content="Do you know Messi?")],
            "intent": "",
            "specialist": "",
            "order_id": "",
            "tracking_number": "",
            "customer_email": "qa@example.test",
            "tool_results": {},
            "final_response": "",
            "retry_count": 0,
            "error_message": "",
        })

        assert "ShopAssist's support assistant" in result["final_response"]
        assert "general-knowledge" in result["final_response"]
        assert not result["error_message"]


class TestLLMConfiguration:
    def test_groq_is_default_provider(self):
        from src.config import Settings

        config = Settings(_env_file=None)

        assert config.llm_provider == "groq"
        assert config.groq_model == "openai/gpt-oss-20b"

    def test_creates_ollama_chat_model_from_settings(self, monkeypatch):
        import langchain_ollama

        from src.agent import llm
        from src.config import settings

        captured = {}

        class FakeOllama:
            def __init__(self, **kwargs):
                captured.update(kwargs)

        monkeypatch.setattr(settings, "llm_provider", "ollama")
        monkeypatch.setattr(settings, "ollama_model", "llama-test")
        monkeypatch.setattr(settings, "ollama_base_url", "http://ollama.test:11434")
        monkeypatch.setattr(langchain_ollama, "ChatOllama", FakeOllama)
        monkeypatch.setattr(llm, "_llm", None)

        llm.get_llm()

        assert captured["model"] == "llama-test"
        assert captured["base_url"] == "http://ollama.test:11434"
        assert captured["temperature"] == settings.temperature
        assert captured["client_kwargs"] == {"timeout": llm.LLM_TIMEOUT_SECONDS}

    def test_langfuse_host_accepts_base_url_environment_name(self):
        from src.config import Settings

        config = Settings(_env_file=None, LANGFUSE_BASE_URL="https://langfuse.example")

        assert config.langfuse_host == "https://langfuse.example"

    def test_creates_gemini_chat_model_from_settings(self, monkeypatch):
        import langchain_google_genai

        from src.agent import llm
        from src.config import settings

        captured = {}

        class FakeGemini:
            def __init__(self, **kwargs):
                captured.update(kwargs)

        monkeypatch.setattr(settings, "llm_provider", "google")
        monkeypatch.setattr(settings, "gemini_api_key", "test-gemini-key")
        monkeypatch.setattr(settings, "gemini_model", "gemini-test-model")
        monkeypatch.setattr(
            langchain_google_genai, "ChatGoogleGenerativeAI", FakeGemini
        )
        monkeypatch.setattr(llm, "_llm", None)

        llm.get_llm()

        assert captured["model"] == "gemini-test-model"
        assert captured["google_api_key"] == "test-gemini-key"
        assert captured["temperature"] == settings.temperature
        assert captured["timeout"] == llm.LLM_TIMEOUT_SECONDS
        assert captured["max_retries"] == 0

    def test_selected_gemini_requires_api_key(self, monkeypatch):
        from src.agent import llm
        from src.config import settings

        monkeypatch.setattr(settings, "llm_provider", "google")
        monkeypatch.setattr(settings, "gemini_api_key", "")
        monkeypatch.setattr(llm, "_llm", None)

        with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
            llm.get_llm()

    def test_supervisor_falls_back_to_scope_reply_when_llm_is_unavailable(self, monkeypatch):
        from langchain_core.messages import HumanMessage

        from src.agent import llm
        from src.agent.response import response_node
        from src.agent.supervisor import supervisor_node

        def fail_to_initialize():
            raise RuntimeError("Missing Gemini API key")

        monkeypatch.setattr(llm, "get_llm", fail_to_initialize)
        supervisor_result = supervisor_node(
            {"messages": [HumanMessage(content="Can you explain this warranty coverage in detail?")]}
        )

        assert supervisor_result["offline_mode"]
        response = response_node({
            "intent": supervisor_result["intent"],
            "messages": [HumanMessage(content="Can you explain this warranty coverage in detail?")],
            "offline_mode": supervisor_result["offline_mode"],
            "error_message": supervisor_result["error_message"],
            "tool_results": {},
        })
        assert "orders, shipping, products, payments, and returns" in response["final_response"]
        assert "support@shopassist.ai" not in response["final_response"]

    def test_tool_exception_does_not_leak_traceback(self, monkeypatch):
        from langchain_core.messages import AIMessage
        from langchain_core.tools import tool

        from src.agent import llm
        from src.agent.specialists.common import run_specialist

        @tool
        def failing_tool() -> str:
            """Simulate an internal tool failure."""
            raise RuntimeError("private database host and credentials")

        class FakeToolLLM:
            def invoke(self, messages):
                if any(getattr(message, "type", "") == "tool" for message in messages):
                    return AIMessage(
                        content="I couldn't complete that lookup, so I can't confirm the result."
                    )
                return AIMessage(
                    content="",
                    tool_calls=[{
                        "name": "failing_tool",
                        "args": {},
                        "id": "failure-test",
                        "type": "tool_call",
                    }],
                )

        monkeypatch.setattr(llm, "get_llm_with_tools", lambda tools: FakeToolLLM())
        result = run_specialist(
            {"intent": "support_escalation", "messages": [], "retry_count": 0},
            specialist="customer_agent",
            instructions="Use the tool safely.",
            tools=(failing_tool,),
        )

        tool_result = result["tool_results"]["failing_tool"]
        assert "private database host" not in tool_result
        assert "Traceback" not in tool_result
        assert "could not complete" in tool_result
        assert "couldn't complete that lookup" in result["tool_results"]["assistant_message"]

    def test_response_uses_tool_evidence_without_an_extra_llm_call(self):
        from src.agent.response import response_node

        result = response_node({
            "intent": "order_status",
            "tool_results": {"lookup_order": "Order ORD-1001 is in transit."},
            "error_message": "",
        })

        assert "ORD-1001 is in transit" in result["final_response"]

    def test_specialist_keeps_clarification_when_no_tool_is_called(self, monkeypatch):
        from langchain_core.messages import AIMessage

        from src.agent import llm
        from src.agent.specialists.common import run_specialist

        class FakeToolLLM:
            def invoke(self, messages):
                return AIMessage(content="Please provide your order number.")

        monkeypatch.setattr(
            llm, "get_llm_with_tools", lambda tools: FakeToolLLM()
        )

        result = run_specialist(
            {"intent": "order_status", "messages": [], "retry_count": 0},
            specialist="order_agent",
            instructions="Help with orders.",
            tools=(),
        )

        assert result["tool_results"]["assistant_message"] == (
            "Please provide your order number."
        )

    def test_order_status_fast_path_needs_no_llm_and_uses_account_email(
        self, monkeypatch
    ):
        from langchain_core.messages import HumanMessage

        from src.agent import llm
        from src.agent.graph import agent_graph
        from src.agent.tools import order_service

        def unexpected_llm_call():
            pytest.fail("Order-status fast path should not call Gemini.")

        captured = {}

        def get_orders(email):
            captured["email"] = email
            return [
                type("Order", (), {
                    "order_id": "ORD-1001",
                    "status": "in_transit",
                    "tracking_number": "FDX-78901234",
                })()
            ]

        monkeypatch.setattr(llm, "get_llm", unexpected_llm_call)
        monkeypatch.setattr(
            order_service, "get_orders_by_email", get_orders
        )

        result = agent_graph.invoke({
            "messages": [HumanMessage(content="Where is my order?")],
            "intent": "",
            "specialist": "",
            "order_id": "",
            "tracking_number": "",
            "customer_email": "james@example.com",
            "tool_results": {},
            "final_response": "",
            "retry_count": 0,
            "error_message": "",
        })

        assert captured["email"] == "james@example.com"
        assert "ORD-1001" in result["final_response"]
        assert "FDX-78901234" in result["final_response"]

    def test_order_id_fast_path_passes_authenticated_email(self, monkeypatch):
        from langchain_core.messages import HumanMessage

        from src.agent.tools import order_service
        from src.agent.supervisor import supervisor_node

        captured = {}

        order = type("Order", (), {
            "order_id": "ORD-1002",
            "status": "shipped",
            "tracking_number": "UPS-12345678",
        })()

        def get_order(order_id, email):
            captured.update({"order_id": order_id, "email": email})
            return order

        monkeypatch.setattr(
            order_service, "get_order_for_customer", get_order
        )
        result = supervisor_node({
            "messages": [HumanMessage(content="Where is order ord-1002?")],
            "customer_email": "sarah@example.com",
        })

        assert captured == {
            "order_id": "ORD-1002",
            "email": "sarah@example.com",
        }
        assert result["order_id"] == "ORD-1002"
        assert "UPS-12345678" in result["final_response"]

    def test_return_followup_reuses_order_from_cancel_confirmation(self):
        from langchain_core.messages import AIMessage, HumanMessage

        from src.agent.supervisor import supervisor_node

        result = supervisor_node({
            "messages": [
                HumanMessage(content="Confirm cancellation request CAN-123456789ABC."),
                AIMessage(content="Cancellation confirmed for order **ORD-8560**. Request `CAN-123456789ABC` is complete."),
                HumanMessage(content="I changed my mind, return it."),
            ],
            "customer_email": "customer@example.test",
        })

        assert result["intent"] == "return_request"
        assert result["order_id"] == "ORD-8560"
        assert result["return_reason"] == "changed_mind"

    def test_return_order_number_followup_keeps_original_reason(self):
        from langchain_core.messages import AIMessage, HumanMessage

        from src.agent.supervisor import supervisor_node

        result = supervisor_node({
            "messages": [
                HumanMessage(content="I changed my mind, please return it."),
                AIMessage(content="Please share the order number for the item you want to return."),
                HumanMessage(content="ORD-8560"),
            ],
            "customer_email": "customer@example.test",
        })

        assert result["intent"] == "return_request"
        assert result["order_id"] == "ORD-8560"
        assert result["return_reason"] == "changed_mind"

    def test_cancelled_order_return_failure_is_explained_without_generic_fallback(self):
        from src.agent.response import response_node

        result = response_node({
            "intent": "return_request",
            "order_id": "ORD-8560",
            "tool_results": {
                "initiate_return": "❌ Cannot initiate return: Cancelled orders cannot be returned."
            },
        })

        assert "ORD-8560" in result["final_response"]
        assert "already been cancelled" in result["final_response"]
        assert "No return request or refund was created" in result["final_response"]

    def test_missing_order_reply_distinguishes_shipped_and_delivered_orders(
        self, monkeypatch
    ):
        from langchain_core.messages import HumanMessage

        from src.agent.tools import order_service
        from src.agent.supervisor import supervisor_node

        orders = [
            type("Order", (), {
                "order_id": "ORD-1011",
                "status": "shipped",
                "tracking_number": "UPS-11223344",
            })(),
            type("Order", (), {
                "order_id": "ORD-1001",
                "status": "delivered",
                "tracking_number": "FDX-78901234",
            })(),
        ]
        monkeypatch.setattr(
            order_service, "get_orders_by_email", lambda email: orders
        )

        result = supervisor_node({
            "messages": [HumanMessage(content="i didnt get my orders yet")],
            "customer_email": "james@example.com",
        })

        assert "ORD-1011" in result["final_response"]
        assert "ORD-1001" in result["final_response"]
        assert "Which order number haven't you received?" in result["final_response"]
        assert "marked delivered" in result["final_response"]

    def test_workflow_tracing_records_only_node_timing_and_status(self, monkeypatch):
        from src.observability import langfuse_setup as tracing

        monkeypatch.setattr(tracing, "_langfuse_client", None)
        monkeypatch.setattr(tracing, "_langsmith_client", None)

        with tracing.trace_workflow() as trace:
            with tracing.record_node("supervisor"):
                pass
            trace.intent = "order_status"

        summary = trace.summary()
        assert summary["intent"] == "order_status"
        assert summary["steps"][0]["name"] == "supervisor"
        assert summary["steps"][0]["status"] == "completed"
        assert "messages" not in summary
        assert "outputs" not in summary

    def test_workflow_tracing_redacts_unrecognized_intents(self):
        from src.observability.langfuse_setup import WorkflowTrace

        trace = WorkflowTrace(intent="customer@example.com")

        assert trace.summary()["intent"] == "unknown"

    def test_langsmith_node_span_uses_actual_execution_timing(self):
        from src.observability import langfuse_setup as tracing

        class FakeChild:
            def __init__(self, **kwargs):
                self.start_time = kwargs["start_time"]
                self.extra = kwargs["extra"]
                self.end_time = None

            def post(self):
                pass

            def end(self, **kwargs):
                self.end_time = kwargs["end_time"]

            def patch(self):
                pass

        class FakeRoot:
            def __init__(self):
                self.child = None

            def create_child(self, **kwargs):
                self.child = FakeChild(**kwargs)
                return self.child

        root = FakeRoot()
        trace = tracing.WorkflowTrace(langsmith_root=root)
        token = tracing._active_trace.set(trace)
        try:
            with tracing.record_node("supervisor"):
                time.sleep(0.01)
        finally:
            tracing._active_trace.reset(token)

        step = trace.steps[0]
        assert root.child.end_time > root.child.start_time
        assert root.child.extra["metadata"]["duration_ms"] == step["duration_ms"]
        assert root.child.extra["metadata"]["status"] == "completed"
