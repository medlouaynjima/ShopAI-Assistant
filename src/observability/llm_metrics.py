"""In-process aggregate model usage and latency metrics; never stores prompts."""
from datetime import datetime, timezone
from threading import Lock
from time import perf_counter

from src.config import settings

_lock = Lock()
_started_at = datetime.now(timezone.utc).isoformat()
_totals = {
    "calls": 0,
    "errors": 0,
    "latency_ms_total": 0.0,
    "input_tokens": 0,
    "output_tokens": 0,
    "usage_reported_calls": 0,
    "cost_estimate_usd": 0.0,
    "priced_calls": 0,
}


def _token_usage(response) -> tuple[int, int] | None:
    usage = getattr(response, "usage_metadata", None) or {}
    if not usage:
        metadata = getattr(response, "response_metadata", None) or {}
        usage = metadata.get("token_usage") or metadata.get("usage") or {}
    prompt = usage.get("input_tokens", usage.get("prompt_tokens"))
    completion = usage.get("output_tokens", usage.get("completion_tokens"))
    if prompt is None or completion is None:
        return None
    try:
        return max(0, int(prompt)), max(0, int(completion))
    except (TypeError, ValueError):
        return None


def record_call(duration_ms: float, response=None, *, error: bool = False) -> None:
    usage = _token_usage(response) if response is not None else None
    with _lock:
        _totals["calls"] += 1
        _totals["errors"] += int(error)
        _totals["latency_ms_total"] += max(0.0, duration_ms)
        if usage is not None:
            input_tokens, output_tokens = usage
            _totals["usage_reported_calls"] += 1
            _totals["input_tokens"] += input_tokens
            _totals["output_tokens"] += output_tokens
            if (
                settings.llm_input_cost_per_1m_usd is not None
                and settings.llm_output_cost_per_1m_usd is not None
            ):
                _totals["cost_estimate_usd"] += (
                    input_tokens * settings.llm_input_cost_per_1m_usd
                    + output_tokens * settings.llm_output_cost_per_1m_usd
                ) / 1_000_000
                _totals["priced_calls"] += 1


def invoke_tracked(model, messages):
    """Invoke a LangChain chat model and record timing/usage without content."""
    started = perf_counter()
    try:
        response = model.invoke(messages)
    except Exception:
        record_call((perf_counter() - started) * 1000, error=True)
        raise
    record_call((perf_counter() - started) * 1000, response)
    return response


def metrics_snapshot() -> dict:
    with _lock:
        data = dict(_totals)
    calls = data["calls"]
    provider = settings.llm_provider.strip().lower()
    model_name = {
        "groq": settings.groq_model,
        "google": settings.gemini_model,
        "openai": settings.openai_model,
        "ollama": settings.ollama_model,
    }.get(provider, "unknown")
    rates_configured = (
        settings.llm_input_cost_per_1m_usd is not None
        and settings.llm_output_cost_per_1m_usd is not None
    )
    return {
        "provider": provider,
        "model": model_name,
        "since": _started_at,
        "calls": calls,
        "errors": data["errors"],
        "average_latency_ms": round(data["latency_ms_total"] / calls, 2) if calls else 0,
        "input_tokens": data["input_tokens"],
        "output_tokens": data["output_tokens"],
        "usage_reported_calls": data["usage_reported_calls"],
        "estimated_cost_usd": round(data["cost_estimate_usd"], 8) if rates_configured else None,
        "cost_rates_configured": rates_configured,
        "cost_estimate_complete": bool(calls) and rates_configured and data["priced_calls"] == calls,
    }
