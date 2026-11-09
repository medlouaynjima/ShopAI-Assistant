"""
Order Service — SQLite-backed order management.
"""
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from src.services.database import get_connection
from src.services.shipping_service import ShippingService


@dataclass
class OrderItem:
    product_name: str
    sku: str
    quantity: int
    price: float


@dataclass
class Order:
    order_id: str
    customer_name: str
    email: str
    items: list[OrderItem]
    status: str  # confirmed, shipped, delivered, cancelled
    total: float
    created_at: str
    shipping_address: str
    tracking_number: Optional[str] = None


def _row_to_order(row) -> Order:
    items = [OrderItem(**i) for i in json.loads(row["items"])]
    return Order(
        order_id=row["order_id"],
        customer_name=row["customer_name"],
        email=row["email"],
        items=items,
        status=row["status"],
        total=row["total"],
        created_at=row["created_at"],
        shipping_address=row["shipping_address"],
        tracking_number=row["tracking_number"],
    )


class OrderService:
    """SQLite-backed order management."""

    def get_order(self, order_id: str) -> Optional[Order]:
        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT * FROM orders WHERE order_id = ?", (order_id.upper(),)
            ).fetchone()
            return _row_to_order(row) if row else None
        finally:
            conn.close()

    def get_orders_by_email(self, email: str) -> list[Order]:
        conn = get_connection()
        try:
            rows = conn.execute(
                "SELECT * FROM orders WHERE email = ? ORDER BY created_at DESC",
                (email.lower(),),
            ).fetchall()
            return [_row_to_order(r) for r in rows]
        finally:
            conn.close()

    def get_cancellable_orders_by_email(self, email: str) -> list[Order]:
        """Return only this customer's orders that may still be cancelled."""
        return [
            order for order in self.get_orders_by_email(email)
            if order.status in {"confirmed", "awaiting_payment"}
        ]

    def get_all_orders(self) -> list[Order]:
        conn = get_connection()
        try:
            rows = conn.execute(
                "SELECT * FROM orders ORDER BY created_at DESC"
            ).fetchall()
            return [_row_to_order(r) for r in rows]
        finally:
            conn.close()

    def search_orders(self, query: str, customer_email: Optional[str] = None) -> list[Order]:
        """Search by order ID, customer name, or product name."""
        conn = get_connection()
        try:
            pattern = f"%{query}%"
            ownership_clause = "AND o.email = ?" if customer_email else ""
            params = [pattern, pattern, pattern]
            if customer_email:
                params.append(customer_email.strip().lower())
            rows = conn.execute(
                f"""SELECT DISTINCT o.* FROM orders o
                   WHERE (o.order_id LIKE ?
                      OR o.customer_name LIKE ?
                      OR o.items LIKE ?)
                      {ownership_clause}
                   ORDER BY o.created_at DESC""",
                params,
            ).fetchall()
            return [_row_to_order(r) for r in rows]
        finally:
            conn.close()

    def get_order_for_customer(self, order_id: str, customer_email: str) -> Optional[Order]:
        order = self.get_order(order_id)
        if order and order.email.strip().lower() == customer_email.strip().lower():
            return order
        return None

    def owns_tracking_number(self, tracking_number: str, customer_email: str) -> bool:
        conn = get_connection()
        try:
            row = conn.execute(
                """SELECT 1 FROM orders
                   WHERE tracking_number = ? AND lower(email) = ? LIMIT 1""",
                (tracking_number.strip().upper(), customer_email.strip().lower()),
            ).fetchone()
            return row is not None
        finally:
            conn.close()

    def can_return(self, order_id: str) -> tuple[bool, str]:
        """Check return eligibility using the verified delivery event, not purchase date."""
        order = self.get_order(order_id)
        if not order:
            return False, f"Order {order_id} not found."
        if order.status == "cancelled":
            return False, "Cancelled orders cannot be returned."
        if order.status != "delivered":
            return False, f"Order has not been delivered yet (status: {order.status})."

        shipment = ShippingService().track(order.tracking_number or "")
        if not shipment or shipment.status != "delivered":
            return False, "Delivery could not be verified. Please contact support to check return eligibility."
        delivered_event = next(
            (event for event in reversed(shipment.events)
             if "deliver" in event.description.casefold()),
            None,
        )
        if not delivered_event:
            return False, "Delivery date could not be verified. Please contact support to check return eligibility."

        try:
            delivered_at = datetime.fromisoformat(delivered_event.timestamp)
        except (TypeError, ValueError):
            return False, "Delivery date could not be verified. Please contact support to check return eligibility."
        if delivered_at.tzinfo is None:
            delivered_at = delivered_at.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) - delivered_at.astimezone(timezone.utc) > timedelta(days=14):
            return False, "The 14-day return window has expired."
        return True, "Order is eligible for return."
