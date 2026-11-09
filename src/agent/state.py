"""
Agent State — the shared state object that flows through the LangGraph.
"""
from typing import Annotated, Any
import operator
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict


class AgentState(TypedDict):
    """The state carried through each node in the graph."""

    # Conversation messages (append-only via `add_messages` reducer)
    messages: Annotated[list, add_messages]

    # Triage classification result
    intent: str
    specialist: str

    # Entities extracted from the user message
    order_id: str
    tracking_number: str
    return_reason: str
    customer_email: str
    # Guest chat is limited to public catalog and policy tools.
    guest_access: bool

    # Tool call results (populated by tool_node)
    tool_results: dict[str, Any]
    tool_events: Annotated[list[dict[str, Any]], operator.add]

    # Final response to the user
    final_response: str

    # Production: retry & error handling
    retry_count: int
    error_message: str
    offline_mode: bool
