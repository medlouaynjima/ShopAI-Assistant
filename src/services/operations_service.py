"""Customer-confirmed order workflows and support escalation."""
import json
import sqlite3
import uuid
from datetime import datetime

from src.services.database import get_connection
from src.services.ticket_triage import triage_ticket


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12].upper()}"


class OperationsService:
    """Coordinates safe, auditable customer-service operations."""

    def list_customer_tickets(self, customer_email: str, limit: int = 25) -> list[dict]:
        email = customer_email.strip().lower()
        conn = get_connection()
        try:
            rows = conn.execute(
                """SELECT ticket_id, order_id, status, category, priority, triage_summary, created_at
                   FROM support_tickets WHERE customer_email = ?
                   ORDER BY created_at DESC LIMIT ?""",
                (email, max(1, min(limit, 50))),
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    def get_pending_cancellation(self, order_id: str, customer_email: str) -> dict | None:
        conn = get_connection()
        try:
            row = conn.execute(
                """SELECT c.* FROM cancellation_requests c
                   JOIN orders o ON o.order_id = c.order_id
                   WHERE c.order_id = ? AND c.status = 'pending_confirmation'
                     AND lower(o.email) = ?
                   ORDER BY c.created_at DESC LIMIT 1""",
                (order_id.strip().upper(), customer_email.strip().lower()),
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def request_cancellation(self, order_id: str, customer_email: str) -> dict:
        conn = get_connection()
        try:
            conn.execute("BEGIN IMMEDIATE")
            order = conn.execute(
                "SELECT order_id, email, status FROM orders WHERE order_id = ?",
                (order_id.strip().upper(),),
            ).fetchone()
            if not order:
                raise LookupError(f"Order {order_id} not found.")
            if order["email"].strip().lower() != customer_email.strip().lower():
                raise PermissionError("The email does not match this order.")
            if order["status"] not in {"confirmed", "awaiting_payment"}:
                raise ValueError(
                    f"Only confirmed or unpaid orders can be cancelled (current status: {order['status']})."
                )

            pending = conn.execute(
                """SELECT * FROM cancellation_requests
                   WHERE order_id = ? AND status = 'pending_confirmation'
                   ORDER BY created_at DESC LIMIT 1""",
                (order["order_id"],),
            ).fetchone()
            if pending:
                conn.commit()
                return dict(pending)

            request = {
                "cancellation_id": _new_id("CAN"),
                "order_id": order["order_id"],
                "status": "pending_confirmation",
                "created_at": datetime.now().isoformat(),
                "confirmed_at": None,
            }
            conn.execute(
                """INSERT INTO cancellation_requests
                   (cancellation_id, order_id, status, created_at, confirmed_at)
                   VALUES (?, ?, ?, ?, ?)""",
                tuple(request.values()),
            )
            conn.commit()
            return request
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def confirm_cancellation(self, cancellation_id: str, customer_email: str) -> dict:
        conn = get_connection()
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """SELECT c.*, o.email, o.status AS order_status
                   FROM cancellation_requests c
                   JOIN orders o ON o.order_id = c.order_id
                   WHERE c.cancellation_id = ?""",
                (cancellation_id.strip().upper(),),
            ).fetchone()
            if not row:
                raise LookupError(f"Cancellation request {cancellation_id} not found.")
            if row["email"].strip().lower() != customer_email.strip().lower():
                raise PermissionError("The email does not match this order.")
            if row["status"] == "confirmed":
                conn.commit()
                return dict(row)
            if row["status"] != "pending_confirmation":
                raise ValueError(f"Cancellation request is {row['status']}.")
            if row["order_status"] not in {"confirmed", "awaiting_payment"}:
                raise ValueError(
                    f"Order can no longer be cancelled (current status: {row['order_status']})."
                )

            confirmed_at = datetime.now().isoformat()
            conn.execute(
                "UPDATE orders SET status = 'cancelled' WHERE order_id = ? AND status IN ('confirmed', 'awaiting_payment')",
                (row["order_id"],),
            )
            conn.execute(
                """UPDATE cancellation_requests
                   SET status = 'confirmed', confirmed_at = ?
                   WHERE cancellation_id = ? AND status = 'pending_confirmation'""",
                (confirmed_at, row["cancellation_id"]),
            )
            conn.commit()
            result = dict(row)
            result.update(status="confirmed", confirmed_at=confirmed_at)
            return result
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def confirm_return(self, rma_number: str, customer_email: str) -> dict:
        conn = get_connection()
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """SELECT r.*, o.email FROM returns r
                   JOIN orders o ON o.order_id = r.order_id
                   WHERE r.rma_number = ?""",
                (rma_number.strip().upper(),),
            ).fetchone()
            if not row:
                raise LookupError(f"Return request {rma_number} not found.")
            if row["email"].strip().lower() != customer_email.strip().lower():
                raise PermissionError("The email does not match this order.")
            if row["status"] == "pending_approval":
                conn.commit()
                return dict(row)
            if row["status"] != "pending_customer_confirmation":
                raise ValueError(f"Return request is {row['status']}.")

            conn.execute(
                """UPDATE returns SET status = 'pending_approval'
                   WHERE rma_number = ? AND status = 'pending_customer_confirmation'""",
                (row["rma_number"],),
            )
            conn.commit()
            result = dict(row)
            result["status"] = "pending_approval"
            return result
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def approve_return(self, rma_number: str) -> dict:
        conn = get_connection()
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM returns WHERE rma_number = ?",
                (rma_number.strip().upper(),),
            ).fetchone()
            if not row:
                raise LookupError(f"Return request {rma_number} not found.")
            if row["status"] == "approved":
                conn.commit()
                return dict(row)
            if row["status"] != "pending_approval":
                raise ValueError(
                    "Return must be confirmed by the customer before it can be approved."
                )

            conn.execute(
                "UPDATE returns SET status = 'approved' WHERE rma_number = ? AND status = 'pending_approval'",
                (row["rma_number"],),
            )
            conn.execute(
                """INSERT INTO admin_audit_log
                   (event_id, action, resource_id, details, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    uuid.uuid4().hex,
                    "return_approved",
                    row["rma_number"],
                    json.dumps({"order_id": row["order_id"]}, separators=(",", ":")),
                    datetime.now().isoformat(),
                ),
            )
            conn.commit()
            result = dict(row)
            result["status"] = "approved"
            return result
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def create_support_ticket(
        self, customer_email: str, description: str, order_id: str = ""
    ) -> dict:
        email = customer_email.strip().lower()
        message = description.strip()
        if not email:
            raise ValueError("Customer email is required.")
        if not message:
            raise ValueError("Ticket description is required.")
        normalized_order_id = order_id.strip().upper()
        if normalized_order_id:
            conn = get_connection()
            try:
                order = conn.execute(
                    "SELECT email FROM orders WHERE order_id = ?",
                    (normalized_order_id,),
                ).fetchone()
            finally:
                conn.close()
            if not order:
                raise ValueError("The referenced order does not exist.")
            if order["email"].strip().lower() != email:
                raise PermissionError("The email does not match this order.")

        ticket = {
            "ticket_id": _new_id("TKT"),
            "customer_email": email,
            "order_id": normalized_order_id or None,
            "description": message,
            "status": "open",
            "created_at": datetime.now().isoformat(),
            **triage_ticket(message),
        }
        conn = get_connection()
        try:
            conn.execute(
                """INSERT INTO support_tickets
                   (ticket_id, customer_email, order_id, description, status, created_at,
                    category, priority, ai_category, ai_priority, triage_summary,
                    suggested_team, triage_reason, triage_confidence, triage_source,
                    subcategory, suggested_next_action)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                tuple(ticket[key] for key in (
                    "ticket_id", "customer_email", "order_id", "description", "status", "created_at",
                    "category", "priority", "ai_category", "ai_priority", "triage_summary",
                    "suggested_team", "triage_reason", "triage_confidence", "triage_source",
                    "subcategory", "suggested_next_action",
                )),
            )
            conn.commit()
            return ticket
        except sqlite3.IntegrityError as exc:
            conn.rollback()
            raise ValueError("The referenced order does not exist.") from exc
        finally:
            conn.close()
