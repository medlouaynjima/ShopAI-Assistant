"""Import the curated real-product catalog into configured PostgreSQL."""
from __future__ import annotations

import csv
from pathlib import Path

from src.config import settings
from src.services.database import get_connection

CATALOG_PATH = Path(__file__).resolve().parents[1] / "catalog" / "real_products.csv"
REQUIRED_FIELDS = {
    "sku", "name", "category", "description", "price", "inventory",
    "source_url", "source_checked",
}


def load_catalog() -> list[dict[str, str]]:
    with CATALOG_PATH.open(newline="", encoding="utf-8-sig") as source:
        reader = csv.DictReader(source)
        if not reader.fieldnames or not REQUIRED_FIELDS.issubset(reader.fieldnames):
            raise ValueError("Catalog is missing one or more required columns.")
        rows = list(reader)

    seen: set[str] = set()
    for row in rows:
        sku = row["sku"].strip().upper()
        if not sku.startswith("MORROW-"):
            raise ValueError("Catalog SKUs must use the MORROW- prefix.")
        if sku in seen:
            raise ValueError(f"Duplicate SKU in catalog: {sku}")
        seen.add(sku)
        if not row["name"].strip() or not row["category"].strip() or not row["description"].strip():
            raise ValueError(f"Product {sku} is missing required text fields.")
        if float(row["price"]) <= 0 or int(row["inventory"]) < 0:
            raise ValueError(f"Product {sku} has an invalid price or inventory value.")
        if not row["source_url"].startswith("https://"):
            raise ValueError(f"Product {sku} has an invalid source URL.")
    return rows


def import_catalog() -> int:
    if not settings.database_url:
        raise RuntimeError("DATABASE_URL must point to PostgreSQL; refusing to import into SQLite.")

    rows = load_catalog()
    conn = get_connection()
    try:
        # Verify PostgreSQL has the application schema before any mutation.
        conn.execute("SELECT sku FROM products LIMIT 0")
        for row in rows:
            conn.execute(
                """INSERT INTO products (sku, name, category, description, price, inventory)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT (sku) DO UPDATE SET
                     name = excluded.name,
                     category = excluded.category,
                     description = excluded.description,
                     price = excluded.price""",
                (
                    row["sku"].strip().upper(), row["name"].strip(),
                    row["category"].strip(), row["description"].strip(),
                    float(row["price"]), int(row["inventory"]),
                ),
            )
        conn.commit()
        return len(rows)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    count = import_catalog()
    print(f"Imported {count} real products into PostgreSQL; inventory is 0 pending verified stock.")
