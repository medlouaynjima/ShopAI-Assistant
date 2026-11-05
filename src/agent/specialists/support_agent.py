"""Customer support escalation specialist."""
from src.agent.specialists.common import run_specialist
from src.agent.state import AgentState
from src.agent.tools import SPECIALIST_TOOLS

INSTRUCTIONS = (
    "You are the Support Specialist. Answer policy questions from the policy tool and "
    "create a support ticket when a customer requests a human or reports an unresolved "
    "complaint. Never promise a resolution that the tools did not confirm."
)


def support_agent_node(state: AgentState) -> dict:
    return run_specialist(
        state,
        specialist="support_agent",
        instructions=INSTRUCTIONS,
        tools=SPECIALIST_TOOLS["support_agent"],
    )
