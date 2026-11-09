# Support operations intelligence report

Updated: 9 November 2026

## Business workflow delivered

ShopAssist captures agent outcomes and tool execution events without storing customer message content in telemetry. Signed-in customers can rate individual answers as helpful, not helpful, or unresolved. Ticket records now carry AI triage recommendations, a human-owned team assignment, internal staff notes, first staff activity, resolution time, and reopen count. The admin queue supports category/priority/status filters, manual overrides, assignment, notes, and review of failed or negatively rated agent turns.

The AI proposes ticket category, priority, summary, subcategory, suggested team, and next action. Humans retain ownership of assignment, queue changes, resolution, cancellations, and return approval.

## Dashboard measures

- Ticket backlog and counts by category/priority.
- Average time to first staff activity, explicitly defined as moving a ticket to in-progress or adding an internal note. It is not a customer-facing first-response time.
- Average time from ticket creation to a human marking it resolved.
- Reopened ticket count.
- Agent latency, tool failure rate, and ticket-creating escalation rate.
- Explicit customer helpfulness feedback; no feedback is shown as unavailable rather than zero.
- A review queue for model errors, tool errors, unsupported/unverified answers, and negative customer feedback.
- Dashboard and ticket views accept date range, category, priority, and status filters. The filter definition separates ticket metrics from agent-turn metrics.

## Verification evidence

- Three isolated SQLite service tests cover customer-scoped feedback, event history, analytics, staff pickup timing, ticket assignment, internal notes, reopen accounting, and review queue closure: **3/3 passed**.
- Deterministic tool and safety workflow evaluation: **20/20 passed** after adapting its tool-failure check for the structured tool-event result.
- MCP authorization checks: **passed** (public product discovery, missing/invalid session rejection, owned-order lookup, and cross-customer denial).
- TypeScript typecheck and Python compilation: **passed**.
- Latest broad local Python suite: **104 passed, 1 skipped, 1 deselected**. The Redis integration test skipped because Redis was unreachable. The excluded API workflow test blocks while Starlette/AnyIO starts its Windows test portal under Python 3.14; the block occurs before its first request. PostgreSQL integration was not run locally because no test server was reachable.
- The official MCP SDK client smoke is present, but its in-process async transport also did not complete in this Python/Windows environment. The synchronous MCP authorization checks did complete successfully.

These checks use generated sample customers and data. They validate application behavior, not service-level results for a real business. The helpfulness measure is opt-in user feedback and is not equivalent to resolution. The current product has no staff reply composer, so it cannot truthfully claim a first customer-facing response metric yet.
