"""Returns and refunds specialist."""
from src.agent.specialists.common import run_specialist
from src.agent.state import AgentState
from src.agent.tools import SPECIALIST_TOOLS

INSTRUCTIONS = (
    "You are the Returns and Refunds Specialist. Ground eligibility in the return tool and "
    "policy. Creating a return only creates a pending request; customer confirmation and "
    "human approval are required. Never claim a refund has been issued."
)


def returns_agent_node(state: AgentState) -> dict:
    return run_specialist(
        state,
        specialist="returns_agent",
        instructions=INSTRUCTIONS,
        tools=SPECIALIST_TOOLS["returns_agent"],
    )
