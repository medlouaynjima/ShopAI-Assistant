from types import SimpleNamespace

from src.observability.llm_metrics import metrics_snapshot, record_call


def test_metrics_record_only_aggregate_latency_tokens_and_configured_cost(monkeypatch):
    from src.config import settings

    monkeypatch.setattr(settings, "llm_input_cost_per_1m_usd", 0.2)
    monkeypatch.setattr(settings, "llm_output_cost_per_1m_usd", 0.8)
    before = metrics_snapshot()
    response = SimpleNamespace(
        usage_metadata={"input_tokens": 100, "output_tokens": 50},
        content="private prompt and answer must not be included in metrics",
    )

    record_call(25, response)
    after = metrics_snapshot()

    assert after["calls"] == before["calls"] + 1
    assert after["input_tokens"] == before["input_tokens"] + 100
    assert after["output_tokens"] == before["output_tokens"] + 50
    assert after["average_latency_ms"] > 0
    assert after["cost_rates_configured"] is True
    assert "private prompt" not in str(after)


def test_metrics_leave_cost_unknown_without_configured_rates(monkeypatch):
    from src.config import settings

    monkeypatch.setattr(settings, "llm_input_cost_per_1m_usd", None)
    monkeypatch.setattr(settings, "llm_output_cost_per_1m_usd", None)
    assert metrics_snapshot()["estimated_cost_usd"] is None
