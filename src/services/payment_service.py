"""Read-only simulated payment lookup for the payment specialist."""
from dataclasses import dataclass

from src.services.database import get_connection


@dataclass
class Payment:
    payment_id: str
    order_id: str
    status: str
    amount: float
    provider: str
    updated_at: str


class PaymentService:
    """Reads demo payment records; it never charges, refunds, or moves funds."""

    def get_for_order(self, order_id: str, customer_email: str) -> Payment | None:
        conn = get_connection()
        try:
            row = conn.execute(
                """SELECT p.* FROM payments p
                   JOIN orders o ON o.order_id = p.order_id
                   WHERE p.order_id = ? AND lower(o.email) = ?""",
                (order_id.strip().upper(), customer_email.strip().lower()),
            ).fetchone()
            return Payment(**dict(row)) if row else None
        finally:
            conn.close()
