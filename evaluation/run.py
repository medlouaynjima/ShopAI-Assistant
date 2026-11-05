"""Run the intent and graph-routing evaluation with the configured LLM."""
import argparse
import json
import sys
import time
from collections.abc import Callable
from pathlib import Path

from langchain_core.messages import HumanMessage

from src.agent.graph import route_from_supervisor
from src.agent.supervisor import supervisor_node

SCENARIO_PATH = Path(__file__).with_name("scenarios.json")
TOOL_INTENTS = {
    "order_status",
    "order_cancellation",
    "shipping_tracking",
    "return_request",
    "return_policy",
    "product_search",
    "payment_status",
    "support_escalation",
}
GENERAL_SCENARIO_GROUPS = {"unknown_policy", "conversational_follow_up"}


def load_scenarios() -> list[dict[str, str]]:
    data = json.loads(SCENARIO_PATH.read_text(encoding="utf-8"))
    scenarios = [
        {
            "expected_intent": "general" if group in GENERAL_SCENARIO_GROUPS else group,
            "message": message,
        }
        for group, messages in data.items()
        for message in messages
    ]
    if len(scenarios) < 100:
        raise ValueError(f"Expected at least 100 scenarios, found {len(scenarios)}.")
    if len({item["message"] for item in scenarios}) != len(scenarios):
        raise ValueError("Evaluation messages must be unique.")
    return scenarios


def evaluate(
    min_accuracy: float,
    request_delay_seconds: float = 0,
    failure_retries: int = 0,
    retry_delay_seconds: float = 65,
    require_live_model: bool = False,
    on_scenario_complete: Callable[[int, dict, dict], None] | None = None,
) -> dict:
    scenarios = load_scenarios()
    failures = []
    correct = 0
    category_totals: dict[str, dict[str, int]] = {}
    for index, scenario in enumerate(scenarios, start=1):
        if index > 1 and request_delay_seconds > 0:
            time.sleep(request_delay_seconds)
        expected = scenario["expected_intent"]
        counts = category_totals.setdefault(expected, {"passed": 0, "total": 0})
        counts["total"] += 1
        state = {
            "messages": [HumanMessage(content=scenario["message"])],
            "customer_email": "",
            "intent": "",
            "specialist": "",
            "order_id": "",
            "tracking_number": "",
            "tool_results": {},
            "final_response": "",
            "retry_count": 0,
            "error_message": "",
        }
        result = {}
        for attempt in range(failure_retries + 1):
            result = supervisor_node(state)
            failed = bool(result.get("error_message")) or (
                require_live_model and bool(result.get("offline_mode"))
            )
            if not failed:
                break
            if attempt < failure_retries:
                time.sleep(retry_delay_seconds)
        if result.get("error_message") or (require_live_model and result.get("offline_mode")):
            raise RuntimeError(
                f"Supervisor failed on scenario {index}: "
                f"{result.get('error_message') or 'used offline fallback; live result unavailable'}"
            )
        if on_scenario_complete is not None:
            on_scenario_complete(index, scenario, result)
        actual = result.get("intent", "general")
        route = route_from_supervisor(result)
        # Straightforward order-status requests may be answered from the signed-in
        # account by the supervisor's database fast path without entering the LLM tool loop.
        expected_route = (
            "response" if result.get("final_response")
            else "agent" if expected in TOOL_INTENTS
            else "response"
        )
        passed = actual == expected and route == expected_route
        correct += int(passed)
        counts["passed"] += int(passed)
        if not passed:
            failures.append({
                "scenario": index,
                "expected": expected,
                "actual": actual,
                "route": route,
                "message": scenario["message"],
            })

    report = {
        "scenario_count": len(scenarios),
        "passed": correct,
        "accuracy": correct / len(scenarios),
        "by_intent": {
            intent: {
                **counts,
                "accuracy": counts["passed"] / counts["total"],
            }
            for intent, counts in sorted(category_totals.items())
        },
        "minimum_accuracy": min_accuracy,
        "failures": failures,
    }
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--min-accuracy", type=float, default=0.8)
    parser.add_argument(
        "--request-delay-seconds",
        type=float,
        default=0,
        help="Wait this many seconds between scenarios to respect provider rate limits.",
    )
    parser.add_argument(
        "--failure-retries",
        type=int,
        default=0,
        help="Retry scenarios when the model provider returns an error.",
    )
    parser.add_argument(
        "--retry-delay-seconds",
        type=float,
        default=65,
        help="Wait this many seconds before retrying a failed scenario.",
    )
    args = parser.parse_args()
    if not 0 <= args.min_accuracy <= 1:
        parser.error("--min-accuracy must be between 0 and 1.")
    if args.request_delay_seconds < 0:
        parser.error("--request-delay-seconds cannot be negative.")
    if args.failure_retries < 0:
        parser.error("--failure-retries cannot be negative.")
    if args.retry_delay_seconds < 0:
        parser.error("--retry-delay-seconds cannot be negative.")

    try:
        report = evaluate(
            args.min_accuracy,
            args.request_delay_seconds,
            args.failure_retries,
            args.retry_delay_seconds,
        )
    except RuntimeError as error:
        print(f"Evaluation aborted: {error}", file=sys.stderr)
        return 2
    print(json.dumps(report, indent=2))
    if report["accuracy"] < args.min_accuracy:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
