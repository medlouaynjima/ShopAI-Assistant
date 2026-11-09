"""Shared ReAct execution for customer-facing agents."""
from collections.abc import Sequence
import logging
import time

from langchain_core.messages import SystemMessage, ToolMessage

from src.agent import llm
from src.agent.fallback import run_offline_tool
from src.agent.state import AgentState
from src.observability.llm_metrics import invoke_tracked

logger = logging.getLogger(__name__)

CUSTOMER_SCOPED_TOOLS = {
    "lookup_order",
    "lookup_orders_by_email",
    "lookup_cancellable_orders",
    "search_orders",
    "track_shipment",
    "check_return_eligibility",
    "request_order_cancellation",
    "initiate_return",
    "create_support_ticket",
}
MAX_TOOL_TURNS = 5


def _run_tool(tool_call: dict, tools: Sequence, state: AgentState, specialist: str) -> tuple[str, str, dict]:
    """Run one requested tool while enforcing server-owned customer identity."""
    tool_name = tool_call.get("name", "")
    tool_args = dict(tool_call.get("args") or {})
    if tool_name in CUSTOMER_SCOPED_TOOLS:
        if tool_name == "lookup_orders_by_email":
            tool_args["email"] = state.get("customer_email", "")
        else:
            tool_args["customer_email"] = state.get("customer_email", "")

    tool = next((item for item in tools if item.name == tool_name), None)
    if tool is None:
        name = tool_name or "unknown_tool"
        return name, f"Tool '{tool_name}' is not available to {specialist}.", {"name": name, "success": False, "duration_ms": 0}
    try:
        started = time.perf_counter()
        result = str(tool.invoke(tool_args))
        event = {"name": tool_name, "success": not result.startswith("❌") and "could not complete" not in result.lower(), "duration_ms": round((time.perf_counter() - started) * 1000)}
        return tool_name, result, event
    except Exception:
        event = {"name": tool_name or "unknown_tool", "success": False, "duration_ms": 0}
        # Keep implementation details out of the model context and customer response.
        return tool_name, "The tool could not complete this lookup. Try another relevant tool or explain the limitation.", event


def _answer_from_evidence(conversation: list, instructions: str) -> str:
    """Use one final model turn to synthesize the evidence if the tool loop is full."""
    synthesis_prompt = f"""{instructions}

The tool-call limit for this request has been reached. Use the tool results already in
the conversation to answer the customer. Do not call tools or expose private reasoning.
Be concise, conversational, and clear about any detail the evidence does not contain."""
    result = invoke_tracked(llm.get_llm(), [SystemMessage(content=synthesis_prompt), *conversation])
    return str(result.content).strip()


def run_specialist(
    state: AgentState,
    *,
    specialist: str,
    instructions: str,
    tools: Sequence,
) -> dict:
    """Let the model choose tools, inspect their results, and write the final answer."""
    intent = state.get("intent", "general")
    messages = state.get("messages", [])
    retries = state.get("retry_count", 0)

    if intent == "general":
        return {"tool_results": {}, "tool_events": [], "retry_count": retries, "specialist": specialist}

    if state.get("offline_mode"):
        fallback_result = run_offline_tool(intent, messages, state, tools)
        if fallback_result:
            tool_name, result = fallback_result
            return {
                "tool_results": {tool_name: result},
                "tool_events": [{"name": tool_name, "success": not str(result).startswith("❌"), "duration_ms": 0}],
                "retry_count": retries,
                "specialist": specialist,
            }
        return {
            "tool_results": {
                "assistant_message": (
                    "I can check orders, shipping, products, policies, and support requests. "
                    "Please tell me what you need help with."
                )
            },
            "tool_events": [],
            "retry_count": retries,
            "specialist": specialist,
        }

    context_prompt = f"""{instructions}

Customer intent: {intent}

Verified context:
- Order ID: {state.get('order_id') or 'unknown'}
- Tracking number: {state.get('tracking_number') or 'unknown'}
- Return reason: {state.get('return_reason') or 'not provided'}
- Signed-in customer email: {state.get('customer_email') or 'unknown'}
- Earlier tool results: {state.get('tool_results') or 'none'}

Work through the request privately. Decide which available tool(s) are needed and call
only those. Read each tool result before deciding whether another lookup is necessary.
For account, inventory, or policy questions, verify the relevant facts with tools before
answering. If a customer asks whether a named product is in stock, search for that product
without filtering out-of-stock results, then report its actual inventory. Use in-stock
filtering only when finding products available to buy.
Then give the customer a direct, natural answer grounded in those results. Do not dump
raw tool output, invent missing details, or reveal private reasoning. For actions, explain
exactly what is pending or completed according to the tool result."""

    conversation = list(messages)
    collected_results: dict[str, str] = {}
    tool_events: list[dict] = []
    try:
        model = llm.get_llm_with_tools(tools)
        for turn_index in range(MAX_TOOL_TURNS):
            ai_message = invoke_tracked(model, [SystemMessage(content=context_prompt), *conversation])
            tool_calls = getattr(ai_message, "tool_calls", None) or []
            if not tool_calls:
                final_text = str(getattr(ai_message, "content", "") or "").strip()
                if not final_text and collected_results:
                    final_text = _answer_from_evidence(conversation, instructions)
                if final_text:
                    collected_results["assistant_message"] = final_text
                return {
                    "tool_results": collected_results,
                    "tool_events": tool_events,
                    "retry_count": retries + 1,
                    "specialist": specialist,
                }

            conversation.append(ai_message)
            for call_index, tool_call in enumerate(tool_calls):
                tool_name, tool_result, tool_event = _run_tool(tool_call, tools, state, specialist)
                tool_events.append(tool_event)
                collected_results[tool_name] = tool_result
                conversation.append(ToolMessage(
                    content=tool_result,
                    tool_call_id=str(
                        tool_call.get("id") or f"{tool_name}-{turn_index}-{call_index}"
                    ),
                    name=tool_name,
                ))

        final_text = _answer_from_evidence(conversation, instructions)
        if final_text:
            collected_results["assistant_message"] = final_text
        return {
            "tool_results": collected_results,
            "tool_events": tool_events,
            "retry_count": retries + 1,
            "specialist": specialist,
        }

    except Exception as error:
        logger.warning(
            "Customer agent model call failed; using safe fallback (%s).",
            type(error).__name__,
        )
        try:
            fallback_result = run_offline_tool(intent, messages, state, tools)
        except Exception as fallback_error:
            fallback_result = None
            error = fallback_error
        if fallback_result:
            tool_name, result = fallback_result
            return {
                "tool_results": {tool_name: result},
                "tool_events": [{"name": tool_name, "success": not str(result).startswith("❌"), "duration_ms": 0}],
                "retry_count": retries + 1,
                "specialist": specialist,
                "offline_mode": True,
            }
        return {
            "tool_results": {"error": "The language model is unavailable."},
            "tool_events": tool_events,
            "retry_count": retries + 1,
            "error_message": "The language model is unavailable.",
            "specialist": specialist,
        }
