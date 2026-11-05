"""
Tool Definitions — the functions the agent can call to interact with backend systems.

Uses LangChain's @tool decorator so they are automatically exposed as
OpenAI function-calling tools.
"""
from langchain_core.tools import tool

from src.services.order_service import OrderService
from src.services.shipping_service import ShippingService
from src.services.returns_service import RETURN_REASONS, ReturnsService
from src.services.operations_service import OperationsService
from src.services.product_service import ProductService
from src.services.payment_service import PaymentService
from src.services.knowledge_service import format_evidence

# Singleton service instances
order_service = OrderService()
shipping_service = ShippingService()
returns_service = ReturnsService()
operations_service = OperationsService()
product_service = ProductService()
payment_service = PaymentService()


# ---------------------------------------------------------------------------
# Order tools
# ---------------------------------------------------------------------------

@tool
def lookup_order(order_id: str, customer_email: str = "") -> str:
    """Look up an order by its ID (e.g. ORD-1001).
    Returns order details: items, status, total, tracking number, address.
    Use this when a customer asks about their order status."""
    if not customer_email.strip():
        return "Please sign in before looking up an order."
    order = order_service.get_order_for_customer(order_id, customer_email)
    if not order:
        return f"❌ Order #{order_id} was not found for your account."

    items_str = "\n".join(
        f"  - {it.product_name} (SKU: {it.sku}) x{it.quantity} = ${it.price}"
        for it in order.items
    )
    return (
        f"📦 Order #{order.order_id}\n"
        f"👤 Customer: {order.customer_name}\n"
        f"📧 Email: {order.email}\n"
        f"📅 Date: {order.created_at[:10]}\n"
        f"📌 Status: {order.status}\n"
        f"💰 Total: ${order.total}\n"
        f"🏠 Address: {order.shipping_address}\n"
        f"📦 Tracking: {order.tracking_number or 'Not yet assigned'}\n"
        f"🛒 Items:\n{items_str}"
    )


@tool
def lookup_orders_by_email(email: str = "") -> str:
    """Find all orders associated with a customer email address.
    Use this when a customer asks 'what are my orders?' or gives their email."""
    orders = order_service.get_orders_by_email(email)
    if not orders:
        return f"❌ No orders found for {email}."

    lines = [f"📋 Orders for {email}:\n"]
    for o in orders:
        lines.append(
            f"  • #{o.order_id} — {o.status.upper()} — ${o.total} "
            f"({o.created_at[:10]}) — Tracking: "
            f"{o.tracking_number or 'not yet assigned'}"
        )
    return "\n".join(lines)


@tool
def lookup_cancellable_orders(customer_email: str = "") -> str:
    """Find the signed-in customer's orders that can still be cancelled.
    Use this when the customer asks to cancel an order but hasn't identified which one.
    Never use or request another customer's email address."""
    if not customer_email.strip():
        return "Please sign in before looking up orders."
    orders = order_service.get_cancellable_orders_by_email(customer_email)
    if not orders:
        return "No orders on this account are currently eligible for cancellation."
    return "\n".join(
        f"#{order.order_id} — {order.status.upper()} — ${order.total:.2f} — "
        f"{', '.join(item.product_name for item in order.items)} — {order.created_at[:10]}"
        for order in orders
    )


@tool
def search_orders(query: str, customer_email: str = "") -> str:
    """Search orders by customer name, product name, or partial order ID.
    Use this when a customer gives vague info like 'keyboard order' or 'John's order'."""
    if not customer_email.strip():
        return "Please sign in before searching your orders."
    orders = order_service.search_orders(query, customer_email)
    if not orders:
        return f"❌ No orders found for '{query}'."

    lines = [f"🔍 Search results for '{query}' ({len(orders)} orders):\n"]
    for o in orders:
        items_preview = ", ".join(it.product_name for it in o.items[:2])
        if len(o.items) > 2:
            items_preview += f" +{len(o.items) - 2} more"
        lines.append(
            f"  • #{o.order_id} — {o.customer_name} — {o.status.upper()} — ${o.total}"
            f"\n    📦 {items_preview}"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Shipping tools
# ---------------------------------------------------------------------------

@tool
def track_shipment(tracking_number: str, customer_email: str = "") -> str:
    """Track a shipment by tracking number (e.g. FDX-78901234, UPS-45678901).
    Returns the current status and event history.
    Use this when a customer asks 'where is my package?' or provides a tracking number."""
    if not customer_email.strip() or not order_service.owns_tracking_number(
        tracking_number, customer_email
    ):
        return f"❌ Tracking number {tracking_number} was not found for your account."
    shipment = shipping_service.track(tracking_number)
    if not shipment:
        return f"❌ Tracking number {tracking_number} not found."

    events_str = "\n".join(
        f"  • {e.timestamp[:10]} — {e.location}: {e.description}"
        for e in shipment.events
    )
    status_emoji = {
        "delivered": "✅",
        "in_transit": "🚚",
        "out_for_delivery": "🏠",
        "label_created": "📦",
    }
    emoji = status_emoji.get(shipment.status, "📦")

    return (
        f"{emoji} **{shipment.carrier}** — {tracking_number}\n"
        f"📌 Status: {shipment.status.upper()}\n"
        f"📅 Estimated Delivery: {shipment.estimated_delivery}\n\n"
        f"📋 Tracking History:\n{events_str}"
    )


# ---------------------------------------------------------------------------
# Returns tools
# ---------------------------------------------------------------------------

@tool
def get_return_policy(query: str = "return policy") -> str:
    """Retrieve cited store policy or product evidence for a customer question.
    Use this for return conditions, shipping, payments, support, and product facts.
    If no source matches, the tool clearly says the answer was not found."""
    return format_evidence(query)


@tool
def check_return_eligibility(order_id: str, customer_email: str = "") -> str:
    """Check if an order is eligible for return.
    Use this BEFORE initiating a return, to verify the order can be returned."""
    if not customer_email.strip() or not order_service.get_order_for_customer(
        order_id, customer_email
    ):
        return f"❌ Order {order_id} was not found for your account."
    can, message = order_service.can_return(order_id)
    if can:
        return f"✅ {message}"
    return f"❌ {message}"


@tool
def request_order_cancellation(order_id: str, customer_email: str = "") -> str:
    """Request cancellation of an order.
    Requires the order ID and matching customer email. This only creates a pending
    request; the customer must confirm it before the order is cancelled."""
    if not order_id.strip() or not customer_email.strip():
        return "Please provide the order ID and the email address used for that order."
    request = operations_service.request_cancellation(order_id, customer_email)
    return (
        f"Cancellation request {request['cancellation_id']} for order "
        f"#{request['order_id']} is {request['status']}. "
        "The order has not been cancelled. Customer confirmation is required."
    )


@tool
def initiate_return(order_id: str, reason: str, customer_email: str = "") -> str:
    """Start a return for an order. Requires order_id and a reason.
    Valid reasons: defective, wrong_item, not_as_described, changed_mind, damaged, too_late.
    Also requires the email address used for the order. The request remains pending
    until customer confirmation and human approval."""
    if not order_id.strip() or not customer_email.strip():
        return "Please provide the order ID and the email address used for that order."

    order = order_service.get_order_for_customer(order_id, customer_email)
    if not order:
        return "❌ The email does not match this order."

    # Check eligibility first
    can, msg = order_service.can_return(order_id)
    if not can:
        return f"❌ Cannot initiate return: {msg}"

    normalized_reason = (reason or "").strip().lower()
    if normalized_reason not in RETURN_REASONS:
        valid = ", ".join(sorted(RETURN_REASONS))
        return f"❌ Invalid return reason '{reason}'. Valid reasons: {valid}"

    ret = returns_service.create_return(order_id, normalized_reason, order.total)
    if ret.status == "pending_customer_confirmation":
        next_step = "Customer confirmation and human approval are still required."
    elif ret.status == "pending_approval":
        next_step = "Customer confirmed; this request is awaiting human approval."
    else:
        next_step = "This request was already approved; no payment was transferred."

    return (
        f"✅ Return request recorded.\n\n"
        f"📦 Order: #{ret.order_id}\n"
        f"🔢 RMA Number: **{ret.rma_number}**\n"
        f"💰 Refund Amount: ${ret.refund_amount}\n"
        f"📋 Reason: {ret.reason}\n"
        f"📌 Status: {ret.status}\n\n"
        f"{next_step} No refund has been issued."
    )


@tool
def create_support_ticket(customer_email: str, description: str, order_id: str = "") -> str:
    """Escalate an unresolved complaint or a request to speak with a human.
    Create a support ticket using the customer's email, issue description, and optional order ID."""
    ticket = operations_service.create_support_ticket(
        customer_email, description, order_id
    )
    return (
        f"✅ Support ticket created: {ticket['ticket_id']}\n"
        f"📌 Status: {ticket['status']}\n"
        "A human support representative will follow up."
    )


@tool
def search_products(query: str, category: str = "", in_stock: bool = False) -> str:
    """Search the product catalog by name or category and return price and stock.
    Use for product discovery, availability, and recommendations. Set in_stock when
    the customer specifically asks for available products."""
    products = product_service.search(query, category, in_stock)
    if not products:
        return "No matching products were found in the catalog."
    lines = []
    for product in products:
        stock = f"{product.inventory} in stock" if product.inventory else "out of stock"
        lines.append(
            f"{product.name} ({product.sku}) — ${product.price:.2f}; {stock}. "
            f"{product.description}"
        )
    return "\n".join(lines)


@tool
def check_product_inventory(sku: str) -> str:
    """Check stock for a catalog item by SKU."""
    product = product_service.get_by_sku(sku)
    if not product:
        return f"Product SKU {sku} was not found."
    if not product.inventory:
        return f"{product.name} ({product.sku}) is currently out of stock."
    return f"{product.name} ({product.sku}): {product.inventory} in stock."


@tool
def lookup_payment_status(order_id: str, customer_email: str = "") -> str:
    """Look up the simulated payment status for the signed-in customer's order.
    Read-only demo tool; it does not charge or refund money."""
    if not customer_email.strip():
        return "Sign in before looking up payment information."
    payment = payment_service.get_for_order(order_id, customer_email)
    if not payment:
        return f"No payment record for order {order_id} was found in your account."
    return (
        f"Payment {payment.payment_id} for order {payment.order_id}: "
        f"{payment.status.upper()}, ${payment.amount:.2f} via {payment.provider}. "
        f"Last updated {payment.updated_at}. This demo does not perform payments."
    )


# ---------------------------------------------------------------------------
# Aggregate tool list
# ---------------------------------------------------------------------------

ALL_TOOLS = [
    lookup_order,
    lookup_orders_by_email,
    lookup_cancellable_orders,
    search_orders,
    track_shipment,
    get_return_policy,
    check_return_eligibility,
    request_order_cancellation,
    initiate_return,
    create_support_ticket,
    search_products,
    check_product_inventory,
    lookup_payment_status,
]

SPECIALIST_TOOLS = {
    "order_agent": [
        lookup_order,
        lookup_orders_by_email,
        lookup_cancellable_orders,
        search_orders,
        track_shipment,
        request_order_cancellation,
    ],
    "returns_agent": [
        get_return_policy,
        check_return_eligibility,
        initiate_return,
    ],
    "product_agent": [search_products, check_product_inventory],
    "payment_agent": [lookup_payment_status],
    "support_agent": [get_return_policy, create_support_ticket],
}
