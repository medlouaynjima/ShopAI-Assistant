"""Create a clearly marked demo checkout order without collecting payment."""
import json
import secrets
from datetime import datetime, timezone

from src.services.database import get_connection


class CheckoutService:
    def create_demo_order(
        self,
        *,
        email: str,
        customer_name: str,
        shipping_address: str,
        items: list[dict],
    ) -> dict:
        quantities: dict[str, int] = {}
        for item in items:
            sku = item["sku"].strip().upper()
            quantities[sku] = quantities.get(sku, 0) + item["quantity"]

        conn = get_connection()
        try:
            conn.execute("BEGIN IMMEDIATE")
            order_items = []
            total = 0.0
            for sku, quantity in quantities.items():
                product = conn.execute(
                    "SELECT sku, name, price, inventory FROM products WHERE sku = ? AND active = 1",
                    (sku,),
                ).fetchone()
                if not product:
                    raise ValueError(f"{sku} is no longer available. Please refresh your bag.")
                if product["inventory"] < quantity:
                    raise ValueError(
                        f"Only {product['inventory']} of {product['name']} are currently in stock."
                    )
                order_items.append({
                    "product_name": product["name"],
                    "sku": product["sku"],
                    "quantity": quantity,
                    "price": float(product["price"]),
                })
                total += float(product["price"]) * quantity

            created_at = datetime.now(timezone.utc).isoformat()
            order_id = f"ORD-{secrets.token_hex(5).upper()}"
            conn.execute(
                """INSERT INTO orders
                   (order_id, customer_name, email, items, status, total, created_at, shipping_address, tracking_number)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    order_id,
                    customer_name,
                    email.strip().lower(),
                    json.dumps(order_items),
                    "awaiting_payment",
                    round(total, 2),
                    created_at,
                    shipping_address.strip(),
                    None,
                ),
            )
            conn.execute(
                """INSERT INTO payments (payment_id, order_id, status, amount, provider, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    f"PAY-{order_id}",
                    order_id,
                    "not_configured",
                    round(total, 2),
                    "demo",
                    created_at,
                ),
            )
            conn.commit()
            return {
                "order_id": order_id,
                "status": "awaiting_payment",
                "total": round(total, 2),
                "created_at": created_at,
                "tracking_number": None,
                "items": order_items,
            }
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
