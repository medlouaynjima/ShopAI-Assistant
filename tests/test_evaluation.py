import pytest

from evaluation import run
from evaluation.run import TOOL_INTENTS, load_scenarios


def test_evaluation_suite_contains_at_least_100_unique_scenarios():
    scenarios = load_scenarios()

    assert len(scenarios) >= 100
    assert len({scenario["message"] for scenario in scenarios}) == len(scenarios)
    assert all(scenario["expected_intent"] for scenario in scenarios)


def test_evaluation_tool_intents_route_to_agent():
    assert {
        "order_status",
        "order_cancellation",
        "shipping_tracking",
        "return_request",
        "return_policy",
        "product_search",
        "payment_status",
        "support_escalation",
    } <= TOOL_INTENTS


def test_evaluation_aborts_when_supervisor_reports_an_error(monkeypatch):
    monkeypatch.setattr(
        run,
        "load_scenarios",
        lambda: [{"expected_intent": "general", "message": "Hello"}],
    )
    monkeypatch.setattr(
        run,
        "supervisor_node",
        lambda _state: {"error_message": "The AI service is unavailable."},
    )

    with pytest.raises(RuntimeError, match="scenario 1"):
        run.evaluate(min_accuracy=0.8)


def test_evaluation_retries_failed_scenario(monkeypatch):
    monkeypatch.setattr(
        run,
        "load_scenarios",
        lambda: [{"expected_intent": "general", "message": "Hello"}],
    )
    results = iter([
        {"error_message": "Temporary model outage."},
        {"intent": "general"},
    ])
    monkeypatch.setattr(run, "supervisor_node", lambda _state: next(results))
    monkeypatch.setattr(run.time, "sleep", lambda _seconds: None)

    report = run.evaluate(
        min_accuracy=1,
        failure_retries=1,
        retry_delay_seconds=1,
    )

    assert report["accuracy"] == 1


def test_evaluation_accepts_verified_order_database_fast_path(monkeypatch):
    monkeypatch.setattr(
        run,
        "load_scenarios",
        lambda: [{
            "expected_intent": "order_status",
            "message": "Where is my order?",
        }],
    )
    monkeypatch.setattr(
        run,
        "supervisor_node",
        lambda _state: {
            "intent": "order_status",
            "final_response": "Your order is shipped.",
        },
    )

    report = run.evaluate(min_accuracy=1)

    assert report["passed"] == 1
    assert report["accuracy"] == 1
    assert report["failures"] == []


def test_live_evaluation_retries_offline_fallback(monkeypatch):
    monkeypatch.setattr(
        run,
        "load_scenarios",
        lambda: [{"expected_intent": "general", "message": "Hello"}],
    )
    results = iter([
        {"intent": "general", "offline_mode": True},
        {"intent": "general", "offline_mode": False},
    ])
    monkeypatch.setattr(run, "supervisor_node", lambda _state: next(results))
    monkeypatch.setattr(run.time, "sleep", lambda _seconds: None)

    report = run.evaluate(
        min_accuracy=1,
        failure_retries=1,
        require_live_model=True,
    )

    assert report["passed"] == 1


def test_live_evaluation_aborts_instead_of_scoring_offline_fallback(monkeypatch):
    monkeypatch.setattr(
        run,
        "load_scenarios",
        lambda: [{"expected_intent": "general", "message": "Hello"}],
    )
    monkeypatch.setattr(
        run,
        "supervisor_node",
        lambda _state: {"intent": "general", "offline_mode": True},
    )

    with pytest.raises(RuntimeError, match="used offline fallback"):
        run.evaluate(min_accuracy=0, require_live_model=True)
