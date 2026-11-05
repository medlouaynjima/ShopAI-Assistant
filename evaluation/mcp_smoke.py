"""Exercise ShopAssist MCP tools with the official SDK client."""
import anyio
from datetime import datetime, timedelta, timezone
import hashlib
from pathlib import Path
import secrets
import tempfile
import os

from mcp import Client

import src.services.database as database
from src.config import settings
from src.mcp_server import server

def _create_isolated_database(path: Path) -> tuple[str, str, str]:
    settings.database_url = ""
    settings.redis_url = ""
    database.DB_PATH = path
    database.init_db()
    conn = database.get_connection()
    try:
        rows = conn.execute(
            "SELECT order_id, email FROM orders ORDER BY order_id"
        ).fetchall()
        if len(rows) < 2:
            raise RuntimeError("The MCP smoke fixture needs two seeded orders.")
        own_order = rows[0]
        other_order = next((row for row in rows[1:] if row["email"] != own_order["email"]), None)
        if other_order is None:
            raise RuntimeError("The MCP smoke fixture needs orders for two customers.")

        token = secrets.token_urlsafe(32)
        now = datetime.now(timezone.utc)
        conn.execute(
            """INSERT OR IGNORE INTO customers
               (email, full_name, password_hash, verified_at, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (own_order["email"], "MCP test customer", "test-only", now.isoformat(), now.isoformat()),
        )
        conn.execute(
            """INSERT INTO auth_sessions (token_hash, email, expires_at, created_at)
               VALUES (?, ?, ?, ?)""",
            (
                hashlib.sha256(token.encode("ascii")).hexdigest(),
                own_order["email"],
                (now + timedelta(hours=1)).isoformat(),
                now.isoformat(),
            ),
        )
        conn.commit()
        return token, own_order["order_id"], other_order["order_id"]
    finally:
        conn.close()


async def run() -> dict:
    with tempfile.TemporaryDirectory(prefix="shopassist-mcp-") as temp_dir:
        database_path = Path(temp_dir) / "mcp-test.sqlite3"
        token, own_order_id, other_order_id = _create_isolated_database(database_path)
        os.environ.pop("MCP_CUSTOMER_SESSION_TOKEN", None)
        async with Client(server) as client:
            discovered = await client.list_tools()
            names = {tool.name for tool in discovered.tools}
            if names != {"search_products", "lookup_order"}:
                raise AssertionError(f"Unexpected ShopAssist MCP tools: {sorted(names)}")

            product_result = await client.call_tool(
                "search_products", {"query": "Mechanical Keyboard", "in_stock": True}
            )
            product_text = str(product_result.structured_content or {}) + " " + " ".join(
                block.text for block in product_result.content if hasattr(block, "text")
            )
            if product_result.is_error or "Mechanical Keyboard" not in product_text or "SKU-201" not in product_text:
                raise AssertionError("MCP product search did not return the expected catalog data.")

            denied = await client.call_tool("lookup_order", {"order_id": own_order_id})
            if not denied.is_error:
                raise AssertionError("Order lookup must reject callers without a session.")

            os.environ["MCP_CUSTOMER_SESSION_TOKEN"] = token
            own_result = await client.call_tool("lookup_order", {"order_id": own_order_id})
            other_result = await client.call_tool("lookup_order", {"order_id": other_order_id})
            own_data = own_result.structured_content or {}
            other_data = other_result.structured_content or {}
            if own_result.is_error or not own_data.get("found"):
                raise AssertionError("Authenticated owner could not retrieve their order.")
            if other_result.is_error or other_data.get("found"):
                raise AssertionError("Cross-customer order lookup was not denied safely.")

        return {
            "transport": "SDK in-process protocol test; server entrypoint defaults to stdio",
            "client_test": "official MCP Python SDK client, in-process protocol",
            "server": "src.mcp_server",
            "tool_discovery": sorted(names),
            "product_search": "passed",
            "unauthenticated_order": "rejected",
            "authenticated_owner_order": "passed",
            "cross_customer_order": "not found (isolated)",
        }


if __name__ == "__main__":
    print(anyio.run(run))
