import pytest
from langchain_core.messages import HumanMessage

from src.agent import supervisor
from src.agent.fallback import classify_without_llm


@pytest.mark.parametrize(
    "message",
    [
        "Stop the order ORD-1005 if it has not shipped.",
        "I want to withdraw order ORD-1010.",
        "Please remove purchase ORD-1001.",
    ],
)
def test_cancellation_paraphrases_are_classified_by_meaning(message):
    assert classify_without_llm(message) == "order_cancellation"


@pytest.mark.parametrize(
    "message",
    [
        "I need the transaction status linked to ORD-1010.",
        "Was payment for ORD-1002 successful?",
    ],
)
def test_payment_status_paraphrases_are_classified(message, monkeypatch):
    assert classify_without_llm(message) == "payment_status"

    def unexpected_llm_call():
        raise AssertionError("Clear payment status questions should not call the LLM")

    monkeypatch.setattr(supervisor.llm, "get_llm", unexpected_llm_call)
    result = supervisor.supervisor_node({
        "messages": [HumanMessage(content=message)],
        "customer_email": "customer@example.com",
    })

    assert result["intent"] == "payment_status"


@pytest.mark.parametrize(
    "message",
    [
        "Does the store offer custom engraving on products?",
        "Can you guarantee an exact delivery time for tomorrow?",
        "Can you guarantee a specific refund arrival date?",
    ],
)
def test_unsupported_store_capabilities_and_guarantees_stay_general(message):
    assert classify_without_llm(message) in (None, "general")


@pytest.mark.parametrize(
    "content",
    [
        '{"intent":"payment_status","order_id":"ORD-1010"}',
        "Result: ```json\n{\"intent\":\"payment_status\",\"order_id\":\"ORD-1010\"}\n```",
        [{"type": "text", "text": '{"intent":"payment_status","order_id":"ORD-1010"}'}],
    ],
)
def test_supervisor_parser_extracts_complete_json_responses(content):
    result = supervisor._decode_classification(content)

    assert result["intent"] == "payment_status"
    assert result["order_id"] == "ORD-1010"


def test_groq_supervisor_uses_strict_json_schema(monkeypatch):
    from langchain_core.messages import AIMessage

    from src.config import settings

    class StructuredOutputFake:
        response_format = None

        def bind(self, **kwargs):
            self.response_format = kwargs["response_format"]
            return self

        def invoke(self, _messages):
            return AIMessage(content=(
                '{"intent":"general","order_id":"","tracking_number":"",'
                '"return_reason":"","needs_tool":false,"tool_name":""}'
            ))

    fake = StructuredOutputFake()
    monkeypatch.setattr(settings, "llm_provider", "groq")
    monkeypatch.setattr(supervisor.llm, "get_llm", lambda: fake)

    result = supervisor.supervisor_node({
        "messages": [HumanMessage(content="What can you help me with?")],
        "customer_email": "customer@example.com",
    })

    assert fake.response_format == supervisor.GROQ_SUPERVISOR_RESPONSE_FORMAT
    assert result["intent"] == "general"


@pytest.mark.parametrize(
    "message",
    [
        "Stop the order ORD-1005 if it has not shipped.",
        "I want to withdraw order ORD-1010.",
    ],
)
def test_cancellation_paraphrases_are_not_misrouted_to_order_fast_path(message, monkeypatch):
    def unexpected_llm_call():
        raise AssertionError("Clear cancellation requests should not call the LLM")

    monkeypatch.setattr(supervisor.llm, "get_llm", unexpected_llm_call)
    result = supervisor.supervisor_node({
        "messages": [HumanMessage(content=message)],
        "customer_email": "customer@example.com",
    })

    assert result["intent"] == "order_cancellation"
    assert result["order_id"]
    assert "final_response" not in result
