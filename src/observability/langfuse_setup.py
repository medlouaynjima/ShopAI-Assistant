"""Privacy-conscious workflow tracing to LangSmith and Langfuse."""
import logging
import sys
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timezone
from time import perf_counter
from typing import Any

from src.config import settings

logger = logging.getLogger(__name__)

SAFE_INTENTS = frozenset({
    "order_status",
    "order_cancellation",
    "shipping_tracking",
    "return_request",
    "return_policy",
    "product_search",
    "payment_status",
    "support_escalation",
    "general",
})

_langfuse_client = None
_langsmith_client = None
_active_trace: ContextVar["WorkflowTrace | None"] = ContextVar(
    "shopassist_workflow_trace", default=None
)


@dataclass
class WorkflowTrace:
    """Only store safe workflow metadata; never store user or model content."""

    started_at: float = field(default_factory=perf_counter)
    steps: list[dict[str, Any]] = field(default_factory=list)
    status: str = "completed"
    intent: str = "unknown"
    langsmith_root: Any = field(default=None, repr=False)

    def summary(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "intent": self.intent if self.intent in SAFE_INTENTS else "unknown",
            "steps": self.steps,
            "duration_ms": round((perf_counter() - self.started_at) * 1000),
        }


def init_observability() -> None:
    """Initialize configured tracing clients without making startup depend on them."""
    global _langfuse_client, _langsmith_client

    if _langfuse_client is None and settings.langfuse_public_key and settings.langfuse_secret_key:
        try:
            from langfuse import Langfuse

            _langfuse_client = Langfuse(
                public_key=settings.langfuse_public_key,
                secret_key=settings.langfuse_secret_key,
                base_url=settings.langfuse_host,
            )
            logger.info("Langfuse workflow tracing enabled.")
        except Exception:
            logger.exception("Could not initialize Langfuse tracing.")
    elif settings.langfuse_public_key or settings.langfuse_secret_key:
        logger.warning("Langfuse tracing needs both public and secret keys.")
    else:
        logger.info("Langfuse not configured.")

    if _langsmith_client is None and settings.langsmith_api_key:
        try:
            from langsmith import Client

            _langsmith_client = Client(
                api_key=settings.langsmith_api_key,
                api_url=settings.langsmith_endpoint,
            )
            logger.info(
                "LangSmith workflow tracing enabled for project %s.",
                settings.langsmith_project,
            )
        except Exception:
            logger.exception("Could not initialize LangSmith tracing.")
    else:
        logger.info("LangSmith not configured.")


@contextmanager
def record_node(name: str):
    """Record a graph node's name, elapsed time, and status only."""
    trace = _active_trace.get()
    started_at = perf_counter()
    status = "completed"
    langfuse_scope = None
    langfuse_span = None
    langsmith_child = None
    exception_info = (None, None, None)

    if trace is not None and _langfuse_client is not None:
        try:
            langfuse_scope = _langfuse_client.start_as_current_observation(
                as_type="span",
                name=f"graph.{name}",
                input={"component": name},
            )
            langfuse_span = langfuse_scope.__enter__()
        except Exception:
            logger.exception("Could not start Langfuse node span.")
            langfuse_scope = None

    if trace is not None and trace.langsmith_root is not None:
        try:
            langsmith_child = trace.langsmith_root.create_child(
                name=f"graph.{name}",
                run_type="chain",
                inputs={"component": name},
                start_time=datetime.now(timezone.utc),
                extra={"metadata": {"status": "running"}},
            )
            langsmith_child.post()
        except Exception:
            logger.exception("Could not start LangSmith node span.")
            langsmith_child = None

    try:
        yield
    except Exception:
        status = "error"
        exception_info = sys.exc_info()
        raise
    finally:
        if trace is not None:
            step = {
                "name": name,
                "status": status,
                "duration_ms": round((perf_counter() - started_at) * 1000),
            }
            trace.steps.append(step)

            if langfuse_span is not None:
                try:
                    langfuse_span.update(
                        output={"status": status},
                        metadata={
                            "status": status,
                            "duration_ms": step["duration_ms"],
                        },
                    )
                except Exception:
                    logger.exception("Could not update Langfuse node span.")
                try:
                    langfuse_scope.__exit__(*exception_info)
                except Exception:
                    logger.exception("Could not close Langfuse node span.")

            if langsmith_child is not None:
                try:
                    langsmith_child.end(
                        outputs={"status": status},
                        end_time=datetime.now(timezone.utc),
                    )
                    langsmith_child.extra.setdefault("metadata", {}).update({
                        "status": status,
                        "duration_ms": step["duration_ms"],
                    })
                    langsmith_child.patch()
                except Exception:
                    logger.exception("Could not complete LangSmith node span.")


@contextmanager
def trace_workflow():
    """Export a redacted root trace and graph-node timing spans."""
    trace = WorkflowTrace()
    token = _active_trace.set(trace)
    langfuse_scope = None
    langfuse_root = None
    langsmith_root = None

    if _langfuse_client is not None:
        try:
            langfuse_scope = _langfuse_client.start_as_current_observation(
                as_type="span",
                name="shopassist.chat",
                input={"workflow": "customer_support"},
                metadata={"privacy": "redacted"},
            )
            langfuse_root = langfuse_scope.__enter__()
        except Exception:
            logger.exception("Could not start Langfuse workflow trace.")
            langfuse_scope = None

    if _langsmith_client is not None:
        try:
            from langsmith.run_trees import RunTree

            langsmith_root = RunTree(
                name="shopassist.chat",
                run_type="chain",
                inputs={"workflow": "customer_support"},
                project_name=settings.langsmith_project,
                client=_langsmith_client,
                extra={"metadata": {"privacy": "redacted"}},
            )
            langsmith_root.post()
            trace.langsmith_root = langsmith_root
        except Exception:
            logger.exception("Could not start LangSmith workflow trace.")
            langsmith_root = None

    try:
        yield trace
    except Exception:
        trace.status = "error"
        raise
    finally:
        summary = trace.summary()
        if langfuse_root is not None:
            try:
                langfuse_root.update(output=summary)
            except Exception:
                logger.exception("Could not complete Langfuse workflow trace.")
            finally:
                try:
                    langfuse_scope.__exit__(None, None, None)
                except Exception:
                    logger.exception("Could not close Langfuse workflow trace.")

        if langsmith_root is not None:
            try:
                langsmith_root.end(
                    outputs={
                        "status": trace.status,
                        "intent": summary["intent"],
                        "steps": trace.steps,
                        "duration_ms": summary["duration_ms"],
                    }
                )
                langsmith_root.patch()
            except Exception:
                logger.exception("Could not complete LangSmith workflow trace.")
        _active_trace.reset(token)


def flush_observability() -> None:
    """Flush queued traces during application shutdown."""
    for client, name in (
        (_langfuse_client, "Langfuse"),
        (_langsmith_client, "LangSmith"),
    ):
        if client is not None:
            try:
                client.flush()
            except Exception:
                logger.exception("Could not flush %s traces.", name)
