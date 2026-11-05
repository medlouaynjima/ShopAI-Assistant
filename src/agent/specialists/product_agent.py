"""Product catalog specialist."""
from src.agent.specialists.common import run_specialist
from src.agent.state import AgentState
from src.agent.tools import SPECIALIST_TOOLS

INSTRUCTIONS = (
    "You are the Product Specialist. Use the catalog tools for product details, "
    "availability, and recommendations. Never invent product specifications or stock."
)


def product_agent_node(state: AgentState) -> dict:
    return run_specialist(
        state,
        specialist="product_agent",
        instructions=INSTRUCTIONS,
        tools=SPECIALIST_TOOLS["product_agent"],
    )
