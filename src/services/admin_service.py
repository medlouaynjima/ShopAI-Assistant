"""Admin-only operational queues, analytics, and audit records."""
import json
import uuid
from datetime import datetime

from src.services.database import get_connection

ALLOWED_TICKET_STATUSES = {"open", "in_progress", "resolved"}


class AdminService:
    def list_tickets(self, status: str | None = None, limit: int = 100) -> list[dict]:
        if status and status not in ALLOWED_TICKET_STATUSES:
            raise ValueError("Unsupported ticket status.")
        safe_limit = max(1, min(limit, 200))
        conn = get_connection()
        try:
            if status:
                rows = conn.execute(
                    """SELECT ticket_id, customer_email, order_id, description,
                              status, created_at
                       FROM support_tickets WHERE status = ?
                       ORDER BY created_at DESC LIMIT ?""",
                    (status, safe_limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """SELECT ticket_id, customer_email, order_id, description,
                              status, created_at
                       FROM support_tickets ORDER BY created_at DESC LIMIT ?""",
                    (safe_limit,),
                ).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    def pending_returns(self, limit: int = 100) -> list[dict]:
        safe_limit = max(1, min(limit, 200))
        conn = get_connection()
        try:
            rows = conn.execute(
                """SELECT r.rma_number, r.order_id, r.reason, r.status,
                          r.refund_amount, r.created_at, o.email AS customer_email
                   FROM returns r JOIN orders o ON o.order_id = r.order_id
                   WHERE r.status = 'pending_approval'
                   ORDER BY r.created_at ASC LIMIT ?""",
                (safe_limit,),
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    def recent_audit(self, limit: int = 100) -> list[dict]:
        safe_limit = max(1, min(limit, 200))
        conn = get_connection()
        try:
            rows = conn.execute(
                """SELECT event_id, action, resource_id, details, created_at
                   FROM admin_audit_log ORDER BY created_at DESC LIMIT ?""",
                (safe_limit,),
            ).fetchall()
            return [
                {
                    **dict(row),
                    "details": json.loads(row["details"]),
                }
                for row in rows
            ]
        finally:
            conn.close()

    def dashboard(self) -> dict:
        conn = get_connection()
        try:
            total_orders = conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
            total_customers = conn.execute("SELECT COUNT(*) FROM customers").fetchone()[0]
            open_tickets = conn.execute(
                "SELECT COUNT(*) FROM support_tickets WHERE status IN ('open', 'in_progress')"
            ).fetchone()[0]
            pending_returns = conn.execute(
                "SELECT COUNT(*) FROM returns WHERE status = 'pending_approval'"
            ).fetchone()[0]
            recent = conn.execute(
                """SELECT ticket_id, customer_email, order_id, description,
                          status, created_at
                   FROM support_tickets ORDER BY created_at DESC LIMIT 10"""
            ).fetchall()
            return {
                "total_orders": total_orders,
                "total_customers": total_customers,
                "open_tickets": open_tickets,
                "pending_return_approvals": pending_returns,
                "recent_tickets": [dict(row) for row in recent],
            }
        finally:
            conn.close()

    def update_ticket(self, ticket_id: str, status: str) -> dict:
        if status not in ALLOWED_TICKET_STATUSES:
            raise ValueError("Unsupported ticket status.")
        conn = get_connection()
        try:
            conn.execute("BEGIN IMMEDIATE")
            ticket = conn.execute(
                "SELECT * FROM support_tickets WHERE ticket_id = ?",
                (ticket_id.strip().upper(),),
            ).fetchone()
            if ticket is None:
                raise LookupError(f"Support ticket {ticket_id} was not found.")
            if ticket["status"] != status:
                conn.execute(
                    "UPDATE support_tickets SET status = ? WHERE ticket_id = ?",
                    (status, ticket["ticket_id"]),
                )
                self._audit(
                    conn,
                    "ticket_status_updated",
                    ticket["ticket_id"],
                    {"from": ticket["status"], "to": status},
                )
            conn.commit()
            result = dict(ticket)
            result["status"] = status
            return result
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @staticmethod
    def _audit(conn, action: str, resource_id: str, details: dict) -> None:
        conn.execute(
            """INSERT INTO admin_audit_log
               (event_id, action, resource_id, details, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (
                uuid.uuid4().hex,
                action,
                resource_id,
                json.dumps(details, separators=(",", ":")),
                datetime.now().isoformat(),
            ),
        )
