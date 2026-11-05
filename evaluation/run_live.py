"""Run the configured LLM routing evaluation with safe retries and resumable checkpoints."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
import time
import uuid

import src.services.database as database
from src.config import settings
from evaluation import run

RESULTS_DIR = Path(__file__).with_name("live_results")
CHECKPOINT_PATH = RESULTS_DIR / "110-scenario-groq-json-schema.inprogress.json"
RESULT_PATH = RESULTS_DIR / "110-scenario-groq.json"
PROTOCOL_VERSION = "groq-supervisor-json-schema-v1"


def _write_json_atomic(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--delay-seconds", type=float, default=15.0)
    parser.add_argument("--retry-delay-seconds", type=float, default=65.0)
    parser.add_argument("--failure-retries", type=int, default=2)
    args = parser.parse_args()
    if args.delay_seconds < 0 or args.retry_delay_seconds < 0 or args.failure_retries < 0:
        parser.error("delays and failure retries must be non-negative")
    if settings.llm_provider.strip().lower() not in {"groq", "google", "openai"}:
        parser.error("live evaluation requires a configured remote LLM provider")

    scenarios = run.load_scenarios()
    signature = json.dumps(scenarios, ensure_ascii=False, sort_keys=True)
    checkpoint = {
        "protocol_version": PROTOCOL_VERSION,
        "provider": settings.llm_provider,
        "model": settings.groq_model if settings.llm_provider == "groq" else "configured",
        "scenario_signature": signature,
        "completed": [],
    }
    if CHECKPOINT_PATH.exists():
        previous = json.loads(CHECKPOINT_PATH.read_text(encoding="utf-8"))
        if (
            previous.get("protocol_version") != PROTOCOL_VERSION
            or
            previous.get("provider") != checkpoint["provider"]
            or previous.get("model") != checkpoint["model"]
            or previous.get("scenario_signature") != signature
        ):
            raise RuntimeError(
                f"Checkpoint {CHECKPOINT_PATH} does not match the current provider/model/scenarios."
            )
        checkpoint = previous

    # Order lookups in this evaluation use only demo data. Keep them isolated
    # from PostgreSQL and from the project's persistent SQLite database.
    settings.database_url = ""
    settings.redis_url = ""
    database.DB_PATH = Path(tempfile.gettempdir()) / f"shopassist-live-eval-{uuid.uuid4().hex}.db"
    database.init_db()

    completed = checkpoint["completed"]
    original_supervisor = run.supervisor_node
    invocation = {"index": 0}
    last_live_request_at = {"value": None}

    def resumable_supervisor(state):
        invocation["index"] += 1
        index = invocation["index"]
        if index <= len(completed):
            saved = completed[index - 1]
            return {
                "intent": saved["intent"],
                "final_response": "cached database fast-path response" if saved["has_final_response"] else "",
                "offline_mode": False,
            }
        for attempt in range(args.failure_retries + 1):
            previous_request = last_live_request_at["value"]
            if previous_request is not None:
                wait = args.delay_seconds - (time.monotonic() - previous_request)
                if wait > 0:
                    time.sleep(wait)
            last_live_request_at["value"] = time.monotonic()
            result = original_supervisor(state)
            failed = bool(result.get("error_message") or result.get("offline_mode"))
            if not failed:
                return result
            if attempt < args.failure_retries:
                print(
                    f"scenario {index}: provider fallback; retrying in {args.retry_delay_seconds:g}s",
                    flush=True,
                )
                time.sleep(args.retry_delay_seconds)
                last_live_request_at["value"] = time.monotonic() - args.delay_seconds
        raise RuntimeError(
            f"Live evaluation stopped on scenario {index}; provider did not return a live response."
        )

    def checkpoint_scenario(index: int, scenario: dict, result: dict) -> None:
        if index <= len(completed):
            return
        completed.append({
            "message": scenario["message"],
            "expected_intent": scenario["expected_intent"],
            "intent": result.get("intent", "general"),
            "has_final_response": bool(result.get("final_response")),
        })
        checkpoint["completed"] = completed
        checkpoint["updated_at_utc"] = datetime.now(timezone.utc).isoformat()
        _write_json_atomic(CHECKPOINT_PATH, checkpoint)
        if index % 10 == 0 or index == len(scenarios):
            print(f"completed {index}/{len(scenarios)}", flush=True)

    run.supervisor_node = resumable_supervisor
    try:
        report = run.evaluate(
            min_accuracy=0.0,
            request_delay_seconds=0,
            require_live_model=True,
            on_scenario_complete=checkpoint_scenario,
        )
    finally:
        run.supervisor_node = original_supervisor

    report.update({
        "provider": settings.llm_provider,
        "model": settings.groq_model if settings.llm_provider == "groq" else "configured",
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "database": "temporary seeded SQLite (isolated)",
        "live_model_checked": True,
        "evaluation_protocol": PROTOCOL_VERSION,
        "request_delay_seconds": args.delay_seconds,
        "checkpoint_file": CHECKPOINT_PATH.name,
    })
    _write_json_atomic(RESULT_PATH, report)
    CHECKPOINT_PATH.unlink(missing_ok=True)
    print(json.dumps({
        "scenario_count": report["scenario_count"],
        "passed": report["passed"],
        "accuracy": report["accuracy"],
        "by_intent": report["by_intent"],
        "failures": report["failures"],
        "saved_to": str(RESULT_PATH),
    }, indent=2, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
