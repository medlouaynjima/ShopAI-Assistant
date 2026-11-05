"""Local stdio MCP server for public catalog and authenticated order lookups."""
import os

from mcp.server import MCPServer

from src.services.auth_service import AuthService
from src.services.order_service import OrderService
from src.services.product_service import ProductService

server = MCPServer(
    "ShopAssist",
    instructions=(
        "Search public ShopAssist products and look up orders only for the customer "
        "authenticated to this local server process. Never request or accept a "
        "customer email as proof of order ownership."
    ),
)
product_service = ProductService()
order_service = OrderService()
auth_service = AuthService()


def _authenticated_customer_email() -> str:
    token = os.getenv("MCP_CUSTOMER_SESSION_TOKEN", "").strip()
    if not token:
        raise PermissionError("Sign in to ShopAssist before looking up an order.")
    customer = auth_service.get_customer_for_token(token)
    if not customer:
        raise PermissionError("The ShopAssist session is invalid or expired. Sign in again.")
    return customer["email"]


@server.tool()
def search_products(query: str = "", category: str = "", in_stock: bool = False) -> list[dict]:
    """Search the public ShopAssist catalog by terms, category, and availability."""
    if len(query) > 120 or len(category) > 64:
        raise ValueError("Search text is too long.")
    return [
        {
            "sku": item.sku,
            "name": item.name,
            "category": item.category,
            "description": item.description,
            "price": item.price,
            "inventory": item.inventory,
        }
        for item in product_service.search(query, category, in_stock)[:10]
    ]


@server.tool()
def lookup_order(order_id: str) -> dict:
    """Look up an order belonging to the authenticated ShopAssist customer."""
    if not order_id or len(order_id) > 32:
        raise ValueError("Enter a valid order number.")
    email = _authenticated_customer_email()
    order = order_service.get_order_for_customer(order_id.strip(), email)
    if order is None:
        # Do not reveal whether another customer's order ID exists.
        return {"found": False, "message": "Order not found on your account."}
    return {
        "found": True,
        "order_id": order.order_id,
        "status": order.status,
        "items": [item.__dict__ for item in order.items],
        "total": order.total,
        "tracking_number": order.tracking_number,
    }


if __name__ == "__main__":
    # stdio is local to the MCP host. The SDK owns stdout; keep diagnostics off it.
    server.run()
