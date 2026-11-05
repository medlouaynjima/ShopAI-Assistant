"""Order and shipment specialist."""
from src.agent.specialists.common import run_specialist
from src.agent.state import AgentState
from src.agent.tools import SPECIALIST_TOOLS

INSTRUCTIONS = (
    "You are the Order Specialist. Handle order details, order search, shipment tracking, "
    "and cancellation requests. Verify account ownership through the provided tools. "
    "A cancellation tool creates only a pending request; never say the order is cancelled "
    "until a separate customer confirmation is completed. Never claim an email will be "
    "sent or that a refund will be issued unless a tool explicitly confirms it."
)


def order_agent_node(state: AgentState) -> dict:
    return run_specialist(
        state,
        specialist="order_agent",
        instructions=INSTRUCTIONS,
        tools=SPECIALIST_TOOLS["order_agent"],
    )
