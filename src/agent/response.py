"""Grounded customer-facing response node."""
import re

from src.agent.state import AgentState

def response_node(state: AgentState) -> dict:
    """Return specialist text or tool evidence without an extra LLM request."""
    if state.get("final_response"):
        return {"final_response": state["final_response"]}

    intent = state.get("intent", "general")
    tool_results = state.get("tool_results", {})

    if state.get("error_message"):
        return {
            "final_response": (
                "Morrow support is temporarily unavailable, so I couldn't complete "
                "your request. Please try again shortly. If you were asking to change "
                "an order, check its current status before retrying."
            )
        }

    if intent == "general" and state.get("offline_mode"):
        last_user_message = ""
        for message in reversed(state.get("messages", [])):
            if getattr(message, "type", "") == "human":
                content = message.content
                last_user_message = content if isinstance(content, str) else str(content)
                break
        normalized = last_user_message.lower()
        if re.search(r"\b(how am i|who am i|do you know me)\b", normalized):
            response = (
                "I don't know how you're feeling or personal details you haven't shared. "
                "I only use your signed-in account to look up ShopAssist information."
            )
        elif re.search(r"\b(messi|capital of|who won|what year)\b", normalized):
            response = (
                "I'm ShopAssist's support assistant, so I focus on orders, shipping, "
                "products, payments, and returns. I can't answer that general-knowledge "
                "question while my AI service is unavailable."
            )
        elif re.search(r"\b(how are you|how.s it going|how do you feel)\b", normalized):
            response = "I'm ready to help with your ShopAssist questions. What can I help you with?"
        else:
            response = (
                "I'm ShopAssist's support assistant. I can help with your orders, shipping, "
                "products, payments, and returns."
            )
        return {"final_response": response}

    if intent == "general" and not tool_results:
        return {
            "final_response": (
                "Hello! I’m Morrow’s shopping assistant. I can help you find products, "
                "check store policies, or—when you’re signed in—look into your orders. "
                "What are you looking for?"
            )
        }

    return_result = tool_results.get("initiate_return")
    if intent == "return_request" and return_result and str(return_result).startswith("❌"):
        detail = str(return_result).removeprefix("❌ Cannot initiate return:").removeprefix("❌").strip()
        order_id = state.get("order_id")
        if "cancelled orders cannot be returned" in detail.lower():
            response = (
                f"Order **{order_id}** has already been cancelled, so it can't be returned. "
                "No return request or refund was created."
            ) if order_id else "This order has already been cancelled, so it can't be returned. No return request or refund was created."
        elif "email does not match" in detail.lower():
            response = "I couldn't verify that order on your account, so I didn't create a return request."
        else:
            response = (
                f"I couldn't start a return for **{order_id}**: {detail} "
                "No return request or refund was created."
            ) if order_id else f"I couldn't start the return: {detail} No return request or refund was created."
        return {"final_response": response}

    specialist_message = tool_results.get("assistant_message")
    if specialist_message:
        return {"final_response": specialist_message}

    if state.get("offline_mode") and tool_results:
        evidence = "\n\n".join(str(result) for result in tool_results.values())
        return {
            "final_response": (
                "I checked the live store data. Here is what it confirms:\n\n"
                f"{evidence}\n\n"
                "My AI response service is temporarily unavailable, so I can't give a "
                "tailored recommendation or interpret details beyond this data right now."
            )
        }

    if any(
        str(result).startswith("❌") or "error" in str(result).lower()
        for result in tool_results.values()
    ):
        return {
            "final_response": (
                "I couldn't retrieve that information just now. Please try again shortly. "
                "If you asked about an order, check that you used an order linked to your account."
            )
        }

    if tool_results:
        evidence = "\n\n".join(str(result) for result in tool_results.values())
        return {
            "final_response": (
                f"Here's what I found:\n\n{evidence}\n\n"
                "Is there anything else I can help you with?"
            )
        }

    return {
        "final_response": (
            "I couldn't find the information needed to answer that. "
            "Could you share a little more detail?"
        )
    }
