"""Payment status specialist."""
from src.agent.specialists.common import run_specialist
from src.agent.state import AgentState
from src.agent.tools import SPECIALIST_TOOLS

INSTRUCTIONS = (
    "You are the Payment Specialist. Use the read-only simulated payment lookup. "
    "Never claim to charge, refund, or change payment state."
)


def payment_agent_node(state: AgentState) -> dict:
    return run_specialist(
        state,
        specialist="payment_agent",
        instructions=INSTRUCTIONS,
        tools=SPECIALIST_TOOLS["payment_agent"],
    )
