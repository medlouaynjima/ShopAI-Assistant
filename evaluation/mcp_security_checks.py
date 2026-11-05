"""Synchronous checks of ShopAssist MCP authorization and data ownership."""
from datetime import datetime, timedelta, timezone
import hashlib
import os
from pathlib import Path
import secrets
import tempfile

from src.config import settings
import src.services.database as database
from src.mcp_server import lookup_order, search_products, server


def run() -> dict:
    settings.database_url = ""
    settings.redis_url = ""
    with tempfile.TemporaryDirectory(prefix="shopassist-mcp-check-") as temp_dir:
        database.DB_PATH = Path(temp_dir) / "mcp-check.sqlite3"
        database.init_db()
        conn = database.get_connection()
        try:
            rows = conn.execute(
                "SELECT order_id, email FROM orders ORDER BY order_id"
            ).fetchall()
            own = rows[0]
            other = next(row for row in rows[1:] if row["email"] != own["email"])
            created = datetime.now(timezone.utc)
            created_iso = created.isoformat()
            conn.execute(
                """INSERT OR IGNORE INTO customers
                   (email, full_name, password_hash, verified_at, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (own["email"], "MCP test customer", "test-only", created_iso, created_iso),
            )
            token = secrets.token_urlsafe(32)
            conn.execute(
                """INSERT INTO auth_sessions (token_hash, email, expires_at, created_at)
                   VALUES (?, ?, ?, ?)""",
                (
                    hashlib.sha256(token.encode("ascii")).hexdigest(),
                    own["email"],
                    (created + timedelta(hours=1)).isoformat(),
                    created.isoformat(),
                ),
            )
            conn.commit()
        finally:
            conn.close()

        registered_tools = {tool.name for tool in server._tool_manager.list_tools()}
        if registered_tools != {"search_products", "lookup_order"}:
            raise AssertionError("ShopAssist MCP tool registration is incomplete.")

        products = search_products("Mechanical Keyboard", in_stock=True)
        if not any(product["sku"] == "SKU-201" for product in products):
            raise AssertionError("Public product lookup returned no expected product.")

        os.environ.pop("MCP_CUSTOMER_SESSION_TOKEN", None)
        try:
            lookup_order(own["order_id"])
            raise AssertionError("Order lookup allowed an unauthenticated request.")
        except PermissionError:
            pass

        os.environ["MCP_CUSTOMER_SESSION_TOKEN"] = token
        own_result = lookup_order(own["order_id"])
        other_result = lookup_order(other["order_id"])
        if not own_result["found"]:
            raise AssertionError("An authenticated customer could not retrieve their order.")
        if other_result["found"] or "order not found" not in other_result["message"].lower():
            raise AssertionError("Cross-customer order lookup exposed order data.")

        os.environ["MCP_CUSTOMER_SESSION_TOKEN"] = "revoked-or-invalid-token"
        try:
            lookup_order(own["order_id"])
            raise AssertionError("Order lookup accepted an invalid session.")
        except PermissionError:
            pass

    return {
        "registered_tools": sorted(registered_tools),
        "public_product_lookup": "passed",
        "missing_session_rejected": "passed",
        "owned_order_lookup": "passed",
        "cross_customer_lookup": "denied without disclosing existence",
        "invalid_session_rejected": "passed",
    }


if __name__ == "__main__":
    print(run())
