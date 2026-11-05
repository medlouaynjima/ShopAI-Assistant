# ShopAssist Phase 1 AI Evaluation Report

**Date:** 5 November 2026  
**Model:** `openai/gpt-oss-20b` via Groq  
**Routing dataset:** 110 live-model scenarios  
**Database:** temporary seeded SQLite; no customer or production database used

## Routing result

| Measure | Original baseline | Updated run | Change |
|---|---:|---:|---:|
| Correct routes | 101/110 (91.8%) | 110/110 (100%) | +9 cases, +8.2 percentage points |
| General questions | 24/30 (80%) | 30/30 (100%) | +6 |
| Cancellation | 8/10 (80%) | 10/10 (100%) | +2 |
| Payment status | 9/10 (90%) | 10/10 (100%) | +1 |
| Other six intents | 60/60 (100%) | 60/60 (100%) | no change |

The updated run used strict structured output from the supervisor. The complete machine-readable results are in [`110-scenario-groq.json`](live_results/110-scenario-groq.json); the preserved baseline is [`110-scenario-groq-before-phase1.json`](live_results/110-scenario-groq-before-phase1.json).

### Baseline failures now passing

| Scenario | User wording | Baseline route | Expected route |
|---:|---|---|---|
| 15 | “Stop the order ORD-1005 if it has not shipped.” | Order status | Cancellation |
| 20 | “I want to withdraw order ORD-1010.” | Order status | Cancellation |
| 70 | “I need the transaction status linked to ORD-1010.” | Order status | Payment status |
| 91 | “Does the store offer custom engraving on products?” | Product search | General / unsupported service question |
| 92 | “Can you guarantee an exact delivery time for tomorrow?” | Order status | General / unsupported guarantee |
| 94 | “Do you sell replacement parts for old devices?” | Product search | General / unsupported product question |
| 95 | “Can I exchange a product at a physical store?” | Return policy | General / unsupported service question |
| 97 | “Is gift wrapping offered at checkout?” | Product search | General / unsupported service question |
| 99 | “Can you guarantee a specific refund arrival date?” | Payment status | General / unsupported guarantee |

The updated result records zero routing failures. This measures intent routing only; it does not prove that every chosen tool executes correctly or that every final answer is factually complete.

## Broader agent-quality evaluation

The live tool-quality runner covers product lookup, owned order lookup, shipment tracking, policy retrieval, payment lookup, cancellation, returns, ticket creation, cross-customer isolation, and unauthorized cancellation. It uses an isolated temporary database and checks selected tools, arguments, tool evidence, answer requirements, and safety outcomes.

**Status: inconclusive; no quality percentages are reported.** The provider returned `RateLimitError` during the cancellation case after the first five cases had begun/completed model calls. The runner intentionally stopped on offline fallback, and it does not persist a partial report, so those calls cannot be scored reliably from saved evidence. The failure is a provider rate limit, not a demonstrated application regression. Run this suite again when Groq quota is available; the runner now waits 12 seconds between cases.

| Quality dimension | Result |
|---|---|
| Tool selection accuracy | Not measured to completion |
| Tool argument correctness | Not measured to completion |
| Tool execution success | Not measured to completion |
| Final answer correctness | Not measured to completion |
| Policy compliance | Not measured to completion |
| Customer data isolation | Not measured to completion |
| Unauthorized action rejection | Not measured to completion |

## Scope and limitations

- The 110 scenarios are a project evaluation set, not an independent benchmark.
- Only the Groq supervisor routing path was fully live-evaluated in this run.
- Tool and security assertions have not yet been certified by a complete live run.
- PostgreSQL integration was not exercised; evaluation used disposable SQLite.
- The run makes no claim about availability, latency, cost, production readiness, or real payment/shipping integrations.
