"""Grounded, deterministic handling for clear requests when the LLM is offline."""
import re
from collections.abc import Sequence

from src.agent.entities import ORDER_ID_PATTERN, extract_order_id

TRACKING_PATTERN = re.compile(r"\b(?:FDX|UPS|DHL)[-\s]?\d{6,}\b", re.IGNORECASE)
CANCELLATION_ACTION_PATTERN = re.compile(
    r"\b(?:cancel|cancellation|withdraw|withdrawal|stop|remove|delete|void)\b",
    re.IGNORECASE,
)
CANCELLATION_TARGET_PATTERN = re.compile(
    r"\b(?:order|purchase)\b|\bORD[-\s]?\d{3,}\b", re.IGNORECASE
)


def classify_without_llm(message: str) -> str | None:
    """Return an intent only when explicit wording makes the route clear."""
    text = message.lower()
    if re.fullmatch(
        r"\s*(hi|hello|hey|thanks|thank you|good morning|good afternoon)[!.?,\s]*",
        text,
    ):
        return "general"
    # Requests for guarantees or exact timing cannot be fulfilled by looking up
    # an order or refund record; leave them for the general, limitation-aware path.
    if (
        re.search(r"\b(?:guarantee|promise|exact|specific)\b", text)
        and re.search(r"\b(?:delivery|shipping|arrival|refund|eta|time|date)\b", text)
    ):
        return "general"
    if TRACKING_PATTERN.search(text) or re.search(r"\b(track|tracking|shipment)\b", text):
        return "shipping_tracking"
    if (
        CANCELLATION_ACTION_PATTERN.search(text)
        and CANCELLATION_TARGET_PATTERN.search(text)
    ):
        return "order_cancellation"
    if re.search(r"\b(return policy|refund policy|return window|return period|policy)\b", text):
        return "return_policy"
    if re.search(r"\b(return|refund|damaged|defective|wrong item|broken)\b", text):
        return "return_request"
    if re.search(r"\b(payment|paid|charge|charged|transaction)\b", text):
        return "payment_status"
    if re.search(r"\b(human|person|representative|agent|someone|complaint|escalate)\b", text):
        return "support_escalation"
    if re.search(r"\b(stock|in stock|available|availability|recommend|catalog)\b", text):
        return "product_search"
    if re.search(r"\b(order|orders|package|parcel|delivery|delivered|arrived)\b", text):
        return "order_status"
    return None


def _last_user_text(messages) -> str:
    for message in reversed(messages or []):
        if getattr(message, "type", "") == "human":
            content = message.content
            return content if isinstance(content, str) else str(content)
    return ""


def _find_tool(tools: Sequence, name: str):
    return next((tool for tool in tools if tool.name == name), None)


def _product_terms(message: str) -> list[str]:
    ignored = {
        "do", "you", "have", "is", "are", "there", "any", "in", "stock",
        "available", "availability", "recommend", "suggest", "find", "search",
        "show", "me", "for", "the", "a", "an", "some", "what", "which",
        "product", "products", "item", "items", "currently", "please", "can",
        "i", "buy", "want", "looking", "with", "and", "or", "this", "that",
    }
    terms = []
    for term in re.findall(r"[a-z0-9]+", message.lower()):
        if term in ignored or len(term) < 2:
            continue
        if term.endswith("ies") and len(term) > 4:
            term = term[:-3] + "y"
        elif term.endswith("s") and not term.endswith("ss") and len(term) > 3:
            term = term[:-1]
        if term not in terms:
            terms.append(term)
    return terms


def run_offline_tool(intent: str, messages, state: dict, tools: Sequence) -> tuple[str, str] | None:
    """Run a safe existing tool for a clear request; return (tool, result)."""
    message = _last_user_text(messages)
    email = str(state.get("customer_email") or "")
    order_id = extract_order_id(message) or str(state.get("order_id") or "").strip().upper()
    args: dict = {}
    tool_name = ""

    if intent == "product_search":
        tool = _find_tool(tools, "search_products")
        terms = _product_terms(message)
        if not tool:
            return None
        if not terms:
            return "assistant_message", "Which product would you like me to check?"
        recommendation = bool(re.search(
            r"\b(recommend|suggest|best|which should|what should)\b",
            message,
            re.IGNORECASE,
        ))
        target_device = next(
            (term for term in terms if term in {"laptop", "computer", "desktop", "phone", "tablet"}),
            None,
        )
        asks_for_accessory = bool(re.search(
            r"\b(accessory|accessories|sleeve|case|charger|cable|stand|cover)\b",
            message,
            re.IGNORECASE,
        ))
        if recommendation and target_device and not asks_for_accessory:
            from src.agent.tools import product_service

            candidates = product_service.search(target_device, in_stock=True)
            accessory_terms = ("sleeve", "case", "charger", "cable", "stand", "cover", "protector")
            candidates = [
                product for product in candidates
                if not any(term in product.name.lower() for term in accessory_terms)
            ]
            if not candidates:
                device_label = "laptop" if target_device == "laptop" else target_device
                return (
                    "assistant_message",
                    f"I couldn't find an in-stock {target_device} in the current catalog. "
                    f"I can search for {device_label} accessories if you'd like."
                )
            return tool.name, str(tool.invoke({"query": target_device, "in_stock": True}))
        last_result = "No matching products were found in the catalog."
        for term in terms:
            last_result = str(tool.invoke({"query": term}))
            if "no matching products" not in last_result.lower():
                if recommendation and "out of stock" in last_result.lower():
                    continue
                return tool.name, last_result
        return tool.name, last_result

    if intent == "return_policy":
        tool_name, args = "get_return_policy", {"query": message}
    elif intent == "shipping_tracking":
        match = TRACKING_PATTERN.search(message)
        if not match:
            return "assistant_message", "Please share the tracking number so I can check the shipment."
        tracking_number = re.sub(r"\s+", "-", match.group(0).upper())
        tool_name, args = "track_shipment", {"tracking_number": tracking_number, "customer_email": email}
    elif intent == "order_status":
        if order_id:
            tool_name, args = "lookup_order", {"order_id": order_id, "customer_email": email}
        else:
            tool_name, args = "lookup_orders_by_email", {"email": email}
    elif intent == "payment_status":
        if not order_id:
            return "assistant_message", "Please share the order number so I can check its payment status."
        tool_name, args = "lookup_payment_status", {"order_id": order_id, "customer_email": email}
    elif intent == "order_cancellation":
        if not order_id:
            tool_name, args = "lookup_cancellable_orders", {"customer_email": email}
        else:
            tool_name, args = "request_order_cancellation", {"order_id": order_id, "customer_email": email}
    elif intent == "return_request":
        if not order_id:
            return "assistant_message", "Please share the order number for the item you want to return."
        reason_map = {
            "defective": "defective", "defect": "defective", "damaged": "damaged",
            "broken": "damaged", "wrong item": "wrong_item", "not as described": "not_as_described",
            "changed my mind": "changed_mind", "change my mind": "changed_mind", "too late": "too_late",
        }
        reason = str(state.get("return_reason") or "") or next(
            (value for phrase, value in reason_map.items() if phrase in message.lower()),
            "",
        )
        if not reason:
            return "assistant_message", "What is the reason for the return (for example, damaged, defective, or wrong item)?"
        tool_name, args = "initiate_return", {"order_id": order_id, "reason": reason, "customer_email": email}
    elif intent == "support_escalation":
        tool_name, args = "create_support_ticket", {"description": message, "customer_email": email, "order_id": order_id}
    else:
        return None

    tool = _find_tool(tools, tool_name)
    if not tool:
        return None
    return tool.name, str(tool.invoke(args))
