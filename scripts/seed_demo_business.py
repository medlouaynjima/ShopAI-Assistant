"""Create a complete, fictional ShopAssist demo business in PostgreSQL."""
from __future__ import annotations

import csv
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.services.auth_service import _password_hash
from src.services.database import get_connection
from scripts.import_real_catalog import load_catalog
from src.config import settings

ROOT = Path(__file__).resolve().parents[1]
ACCOUNTS_PATH = ROOT / "catalog" / "demo_accounts.local.csv"
INITIAL_STOCK = {
    "MORROW-LOGI-MX3S": 12,
    "MORROW-LOGI-MXMECHMINI": 8,
    "MORROW-LOGI-BRIO500": 7,
    "MORROW-SONY-WH1000XM5": 5,
    "MORROW-ANKER-737": 9,
    "MORROW-ANKER-735": 15,
    "MORROW-SAMSUNG-M5-27": 4,
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(days_ago: int = 0, hours_ago: int = 0) -> str:
    return (_now() - timedelta(days=days_ago, hours=hours_ago)).isoformat()


def _load_accounts() -> list[dict[str, str]]:
    with ACCOUNTS_PATH.open(newline="", encoding="utf-8") as source:
        rows = list(csv.DictReader(source))
    if len(rows) != 4 or any(not row.get(k) for row in rows for k in ("full_name", "email", "password")):
        raise ValueError("The local demo accounts file must contain four complete accounts.")
    if len({row["email"].strip().lower() for row in rows}) != len(rows):
        raise ValueError("Demo account email addresses must be unique.")
    if any(not row["email"].strip().lower().endswith("@demo.shopassist.test") for row in rows):
        raise ValueError("Demo accounts must use the reserved demo.shopassist.test domain.")
    return rows


def _make_orders() -> list[dict]:
    return [
        {
            "order_id": "ORD-985001", "email": "olivia.carter@demo.shopassist.test",
            "status": "shipped", "days_ago": 2,
            "items": [
                {"product_name": "Logitech MX Master 3S", "sku": "MORROW-LOGI-MX3S", "quantity": 1, "price": 99.99},
                {"product_name": "Anker 735 Charger (Nano II 65W)", "sku": "MORROW-ANKER-735", "quantity": 1, "price": 29.99},
            ],
            "tracking": "FDX-985001", "payment": "paid",
            "address": "10 Demo Street, Tunis 1000, Tunisia",
        },
        {
            "order_id": "ORD-985002", "email": "olivia.carter@demo.shopassist.test",
            "status": "delivered", "days_ago": 6,
            "items": [
                {"product_name": "Sony WH-1000XM5", "sku": "MORROW-SONY-WH1000XM5", "quantity": 1, "price": 399.99},
            ],
            "tracking": "UPS-985002", "payment": "paid",
            "address": "10 Demo Street, Tunis 1000, Tunisia",
        },
        {
            "order_id": "ORD-985003", "email": "adam.benali@demo.shopassist.test",
            "status": "confirmed", "days_ago": 0,
            "items": [
                {"product_name": "Samsung 27-inch Smart Monitor M5 M50F", "sku": "MORROW-SAMSUNG-M5-27", "quantity": 1, "price": 229.99},
            ],
            "tracking": None, "payment": "pending",
            "address": "22 Demo Avenue, Sfax 3000, Tunisia",
        },
        {
            "order_id": "ORD-985004", "email": "sara.haddad@demo.shopassist.test",
            "status": "delivered", "days_ago": 24,
            "items": [
                {"product_name": "Logitech Brio 500", "sku": "MORROW-LOGI-BRIO500", "quantity": 1, "price": 129.99},
            ],
            "tracking": "UPS-985004", "payment": "paid",
            "address": "5 Demo Lane, Sousse 4000, Tunisia",
        },
        {
            "order_id": "ORD-985005", "email": "yusuf.mansour@demo.shopassist.test",
            "status": "delivered", "days_ago": 3,
            "items": [
                {"product_name": "Anker 737 Power Bank (PowerCore 24K)", "sku": "MORROW-ANKER-737", "quantity": 1, "price": 109.99},
            ],
            "tracking": "FDX-985005", "payment": "paid",
            "address": "8 Demo Road, Monastir 5000, Tunisia",
        },
    ]


def seed_demo_business() -> dict[str, int]:
    if not settings.database_url:
        raise RuntimeError("DATABASE_URL must point to PostgreSQL; refusing to seed SQLite.")

    accounts = _load_accounts()
    catalog = load_catalog()
    orders = _make_orders()
    now = _now()
    conn = get_connection()
    try:
        conn.execute("SELECT sku FROM products LIMIT 0")
        account_emails = [row["email"].strip().lower() for row in accounts]
        placeholders = ", ".join("?" for _ in account_emails)
        existing = conn.execute(
            f"SELECT email FROM customers WHERE email IN ({placeholders})",
            account_emails,
        ).fetchall()
        if len(existing) not in (0, len(accounts)):
            raise RuntimeError("A partial demo account set already exists; refusing to guess passwords or overwrite records.")
        first_seed = not existing

        for product in catalog:
            sku = product["sku"].strip().upper()
            stock = INITIAL_STOCK[sku]
            if first_seed:
                conn.execute(
                    """INSERT INTO products (sku, name, category, description, price, inventory)
                       VALUES (?, ?, ?, ?, ?, ?)
                       ON CONFLICT (sku) DO UPDATE SET
                         name = excluded.name, category = excluded.category,
                         description = excluded.description, price = excluded.price,
                         inventory = excluded.inventory""",
                    (sku, product["name"], product["category"], product["description"], float(product["price"]), stock),
                )
            else:
                conn.execute(
                    """INSERT INTO products (sku, name, category, description, price, inventory)
                       VALUES (?, ?, ?, ?, ?, ?)
                       ON CONFLICT (sku) DO UPDATE SET
                         name = excluded.name, category = excluded.category,
                         description = excluded.description, price = excluded.price""",
                    (sku, product["name"], product["category"], product["description"], float(product["price"]), stock),
                )

        for account in accounts:
            email = account["email"].strip().lower()
            conn.execute(
                """INSERT INTO customers
                   (email, full_name, password_hash, verified_at, created_at)
                   VALUES (?, ?, ?, ?, ?) ON CONFLICT (email) DO NOTHING""",
                (email, account["full_name"].strip(), _password_hash(account["password"]), now.isoformat(), now.isoformat()),
            )

        tracking_rows = {
            "FDX-985001": ("FedEx", "in_transit", 2, "Departed the regional sorting facility"),
            "UPS-985002": ("UPS", "delivered", 6, "Delivered to the front desk"),
            "UPS-985004": ("UPS", "delivered", 24, "Delivered to the front desk"),
            "FDX-985005": ("FedEx", "delivered", 3, "Delivered to the front desk"),
        }
        for tracking, (carrier, status, days_ago, description) in tracking_rows.items():
            events = [{
                "timestamp": _iso(days_ago + 1),
                "location": "Tunis sorting center",
                "description": "Shipment received by carrier",
            }]
            if status == "delivered":
                events.append({
                    "timestamp": _iso(days_ago),
                    "location": "Customer delivery area",
                    "description": description,
                })
            else:
                events.append({
                    "timestamp": _iso(),
                    "location": "Regional sorting center",
                    "description": description,
                })
            conn.execute(
                """INSERT INTO shipments (tracking_number, carrier, status, estimated_delivery, events)
                   VALUES (?, ?, ?, ?, ?) ON CONFLICT (tracking_number) DO NOTHING""",
                (tracking, carrier, status, _iso(days_ago=-2) if status == "in_transit" else _iso(days_ago), json.dumps(events)),
            )

        for order in orders:
            account = next(row for row in accounts if row["email"].strip().lower() == order["email"])
            total = round(sum(item["quantity"] * item["price"] for item in order["items"]), 2)
            conn.execute(
                """INSERT INTO orders
                   (order_id, customer_name, email, items, status, total, created_at, shipping_address, tracking_number)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT (order_id) DO NOTHING""",
                (order["order_id"], account["full_name"], order["email"], json.dumps(order["items"]), order["status"], total,
                 _iso(days_ago=order["days_ago"]), order["address"], order["tracking"]),
            )
            conn.execute(
                """INSERT INTO payments (payment_id, order_id, status, amount, provider, updated_at)
                   VALUES (?, ?, ?, ?, 'demo', ?) ON CONFLICT (payment_id) DO NOTHING""",
                (f"PAY-{order['order_id']}", order["order_id"], order["payment"], total, now.isoformat()),
            )

        # Preload safe, pending examples for return, cancellation, and support workflows.
        conn.execute(
            """INSERT INTO returns (rma_number, order_id, reason, status, refund_amount, created_at)
               VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT (rma_number) DO NOTHING""",
            ("RMA-985002", "ORD-985002", "Item no longer needed", "pending_customer_confirmation", 399.99, now.isoformat()),
        )
        conn.execute(
            """INSERT INTO cancellation_requests (cancellation_id, order_id, status, created_at)
               VALUES (?, ?, ?, ?) ON CONFLICT (cancellation_id) DO NOTHING""",
            ("CAN-985003", "ORD-985003", "pending_confirmation", now.isoformat()),
        )
        conn.execute(
            """INSERT INTO support_tickets (ticket_id, customer_email, order_id, description, status, created_at)
               VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT (ticket_id) DO NOTHING""",
            ("TKT-985005", "yusuf.mansour@demo.shopassist.test", "ORD-985005",
             "Customer reports the package arrived without the charging cable; please verify box contents and follow up.",
             "open", now.isoformat()),
        )

        conn.commit()
        return {
            "products": len(catalog), "customers": len(accounts), "orders": len(orders),
            "shipments": len(tracking_rows), "payments": len(orders),
            "returns": 1, "cancellations": 1, "support_tickets": 1,
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    counts = seed_demo_business()
    print("Seeded ShopAssist demo business in PostgreSQL:")
    for entity, count in counts.items():
        print(f"  {entity}: {count}")
