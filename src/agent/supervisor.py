"""Conversation-aware supervisor for routing customer requests."""
import json
import logging
import re

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from src.agent import llm
from src.observability.llm_metrics import invoke_tracked
from src.agent.entities import ORDER_ID_PATTERN, extract_order_id
from src.agent.fallback import classify_without_llm
from src.agent.state import AgentState
from src.agent.tools import order_service
from src.config import settings

logger = logging.getLogger(__name__)

INTENTS = {
    "order_status", "order_cancellation", "shipping_tracking", "return_request",
    "return_policy", "product_search", "payment_status", "support_escalation", "general",
}
RETURN_REASONS = {
    "changed_mind", "damaged", "defective", "wrong_item", "not_as_described", "too_late",
}
TRACKING_PATTERN = re.compile(r"\b(?:FDX|UPS|DHL)[-\s]?\d{6,}\b", re.IGNORECASE)

SUPERVISOR_PROMPT = """You are the triage and entity-resolution stage of an e-commerce customer support agent.
Read the recent conversation, understand the customer's latest message in context, and output one JSON object:
{"intent":"order_status|order_cancellation|shipping_tracking|return_request|return_policy|product_search|payment_status|support_escalation|general","order_id":"","tracking_number":"","return_reason":"","needs_tool":true,"tool_name":""}

Use conversation context to understand paraphrases, pronouns, short answers, corrections, and follow-ups. For example, if the assistant asked which order and the customer says “the first one”, resolve it from the order list in the conversation. If the assistant asked for an order ID or return reason, use the customer's answer together with the earlier request. If a customer refers to an item/order after a completed action, use the conversation only when the reference is unambiguous. Never invent identifiers or reasons; leave fields empty when unclear.

Choose intent by meaning, not exact keywords. Product questions include availability, features, comparisons, and recommendations. A request to track a package is shipping_tracking; asking general order progress is order_status. A return policy question is return_policy; wanting to return a specific purchase is return_request. Greetings and unrelated small talk are general.

Use product_search only for catalog facts about identifiable products or categories. Questions about store services or capabilities that are not in the product catalog (for example, engraving, gift wrapping, replacement parts, physical-store exchanges, or custom work) are general; do not invent an answer. Requests for guarantees the store data cannot support, such as an exact delivery time or exact refund arrival date, are also general and should be answered with a clear limitation and an offer to check the available order or policy details. Do not route a question to order_status just because it mentions delivery, or to payment_status just because it mentions a refund, unless it asks to look up a particular order's actual status.

Allowed return_reason values: changed_mind, damaged, defective, wrong_item, not_as_described, too_late. Return an empty string if not stated or clearly implied. Do not claim tools were run or actions completed. Cancellation and return tools create requests subject to policy and confirmation; the application enforces those rules.

Return ONLY valid JSON, no markdown or other text."""

GROQ_SUPERVISOR_RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "shopassist_supervisor_classification",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "intent": {"type": "string", "enum": sorted(INTENTS)},
                "order_id": {"type": "string"},
                "tracking_number": {"type": "string"},
                "return_reason": {
                    "type": "string",
                    "enum": ["", *sorted(RETURN_REASONS)],
                },
                "needs_tool": {"type": "boolean"},
                "tool_name": {"type": "string"},
            },
            "required": [
                "intent", "order_id", "tracking_number", "return_reason",
                "needs_tool", "tool_name",
            ],
            "additionalProperties": False,
        },
    },
}


def _conversation_context(messages, limit: int = 12):
    """Pass a bounded, typed slice of recent chat so follow-ups resolve semantically."""
    context = []
    for message in messages[-limit:]:
        if not isinstance(message, (HumanMessage, AIMessage)):
            continue
        content = message.content
        if not isinstance(content, str):
            content = str(content)
        # Avoid sending unbounded pasted content to the classifier.
        context.append(type(message)(content=content[:4000]))
    return context


def _normalize_identifier(value: object, pattern: re.Pattern, prefix: str = "") -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    match = pattern.search(text)
    if not match:
        return ""
    if prefix:
        return f"{prefix}-{match.group(1)}"
    return re.sub(r"\s+", "-", match.group(0).upper())


def _decode_classification(content: object) -> dict:
    if isinstance(content, list):
        text = "".join(
            str(block.get("text", ""))
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        ).strip()
    else:
        text = str(content or "").strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # Some compatible model responses wrap valid JSON in a short preamble.
        # Recover only a complete JSON object; never repair or guess its fields.
        object_start = text.find("{")
        if object_start < 0:
            raise
        data, _ = json.JSONDecoder().raw_decode(text[object_start:])
    if not isinstance(data, dict):
        raise ValueError("Supervisor response must be a JSON object")
    intent = str(data.get("intent", "general")).strip().lower()
    if intent not in INTENTS:
        intent = "general"
    reason = str(data.get("return_reason", "")).strip().lower()
    if reason not in RETURN_REASONS:
        reason = ""
    return {
        "intent": intent,
        "order_id": _normalize_identifier(data.get("order_id"), ORDER_ID_PATTERN, "ORD"),
        "tracking_number": _normalize_identifier(data.get("tracking_number"), TRACKING_PATTERN),
        "return_reason": reason,
    }


def _order_status_fast_path(
    message: str, customer_email: str, order_id: str
) -> dict | None:
    """Resolve straightforward order questions against the signed-in account."""
    try:
        if order_id:
            order = order_service.get_order_for_customer(order_id, customer_email)
            if not order:
                return {
                    "intent": "order_status",
                    "order_id": order_id,
                    "tool_results": {"lookup_order": f"Order {order_id} was not found on this account."},
                    "final_response": f"I couldn't find order **{order_id}** on your account. Please check My orders.",
                    "offline_mode": False,
                }
            tracking = f" Tracking: **{order.tracking_number}**." if order.tracking_number else " Tracking hasn't been assigned yet."
            total = getattr(order, "total", None)
            total_text = f"; total ${total:.2f}" if total is not None else ""
            evidence = f"Order {order.order_id}: {order.status}{total_text}.{tracking}"
            total_reply = f" Total: ${total:.2f}." if total is not None else ""
            return {
                "intent": "order_status",
                "order_id": order.order_id,
                "tool_results": {"lookup_order": evidence},
                "final_response": f"Order **{order.order_id}** is **{order.status.replace('_', ' ')}**.{total_reply}{tracking}",
                "offline_mode": False,
            }

        orders = order_service.get_orders_by_email(customer_email)
        if not orders:
            return {
                "intent": "order_status",
                "order_id": "",
                "tool_results": {"lookup_orders_by_email": "No orders were found for the signed-in account."},
                "final_response": "I couldn't find any orders linked to your account.",
                "offline_mode": False,
            }

        has_missing_delivery = bool(re.search(
            r"\b(didn['’]?t get|haven['’]?t (?:got|received)|not received|missing|never arrived)\b",
            message,
            re.IGNORECASE,
        ))
        if has_missing_delivery:
            lines = []
            for order in orders[:10]:
                if order.status == "delivered":
                    lines.append(f"• **{order.order_id}** is marked delivered (tracking: {order.tracking_number or 'not available'}).")
                else:
                    lines.append(f"• **{order.order_id}** is **{order.status.replace('_', ' ')}** (tracking: {order.tracking_number or 'not assigned yet'}).")
            reply = "I checked the orders on your account:\n\n" + "\n".join(lines) + "\n\nWhich order number haven't you received?"
        elif len(orders) == 1:
            order = orders[0]
            tracking = f" Tracking: **{order.tracking_number}**." if order.tracking_number else " Tracking hasn't been assigned yet."
            reply = f"Your order **{order.order_id}** is **{order.status.replace('_', ' ')}**.{tracking}"
        else:
            lines = [f"• **{order.order_id}** — {order.status.replace('_', ' ')} — ${order.total:.2f}" for order in orders[:10]]
            reply = "Here are the orders linked to your account:\n\n" + "\n".join(lines) + "\n\nWhich order would you like me to check further?"
        evidence = "\n".join(f"{order.order_id}: {order.status}; {order.tracking_number or 'tracking not assigned'}" for order in orders[:10])
        return {
            "intent": "order_status",
            "order_id": "",
            "tool_results": {"lookup_orders_by_email": evidence},
            "final_response": reply,
            "offline_mode": False,
        }
    except Exception as error:
        logger.exception("Account-scoped order fast path failed: %s", type(error).__name__)
        return {
            "intent": "order_status",
            "order_id": order_id,
            "tool_results": {},
            "final_response": "",
            "error_message": "Could not retrieve account orders.",
            "offline_mode": False,
        }


def supervisor_node(state: AgentState) -> dict:
    """Classify the latest message using recent conversation, with safe offline fallback."""
    messages = state.get("messages", [])
    last_user_msg = next(
        (str(message.content) for message in reversed(messages)
         if isinstance(message, HumanMessage)),
        "",
    )
    customer_email = str(state.get("customer_email") or "")
    base = {
        "specialist": "",
        "customer_email": customer_email,
        "error_message": "",
    }
    if not last_user_msg:
        return {**base, "intent": "general", "order_id": "", "tracking_number": ""}

    fallback_intent = classify_without_llm(last_user_msg)
    explicit_order_id = extract_order_id(last_user_msg)
    # Preserve clear high-impact intents when the model returns a plausible but
    # incorrect neighboring route (for example, "withdraw order" or
    # "transaction status" being treated as generic order progress).
    if fallback_intent == "order_cancellation":
        return {
            **base,
            "intent": "order_cancellation",
            "order_id": explicit_order_id,
            "tracking_number": "",
            "return_reason": "",
            "offline_mode": False,
        }
    if (
        fallback_intent == "payment_status"
        and re.search(
            r"\b(status|successful|success|processed|went through|refund)\b",
            last_user_msg,
            re.IGNORECASE,
        )
    ):
        return {
            **base,
            "intent": "payment_status",
            "order_id": explicit_order_id,
            "tracking_number": "",
            "return_reason": "",
            "offline_mode": False,
        }
    if fallback_intent == "order_status":
        fast_path = _order_status_fast_path(
            last_user_msg,
            customer_email,
            explicit_order_id,
        )
        return {**base, **fast_path}

    try:
        model = llm.get_llm()
        if settings.llm_provider.strip().lower() == "groq" and hasattr(model, "bind"):
            model = model.bind(response_format=GROQ_SUPERVISOR_RESPONSE_FORMAT)
        response = invoke_tracked(model, [
            SystemMessage(content=SUPERVISOR_PROMPT),
            *_conversation_context(messages),
        ])
        classification = _decode_classification(response.content)
        return {**base, **classification, "offline_mode": False}
    except Exception as error:
        fallback_intent = classify_without_llm(last_user_msg)
        # Keep entity extraction simple and conservative while the model is unavailable.
        order_match = ORDER_ID_PATTERN.search(last_user_msg)
        tracking_match = TRACKING_PATTERN.search(last_user_msg)
        logger.warning("Supervisor used offline fallback after model failure: %s", type(error).__name__)
        return {
            **base,
            "intent": fallback_intent or "general",
            "order_id": f"ORD-{order_match.group(1).upper()}" if order_match else "",
            "tracking_number": re.sub(r"\s+", "-", tracking_match.group(0).upper()) if tracking_match else "",
            "return_reason": "",
            "offline_mode": True,
        }
