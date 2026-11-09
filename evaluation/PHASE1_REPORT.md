# ShopAssist Phase 1: Customer Support Evaluation

**Updated:** 9 November 2026

**Purpose:** establish a measured baseline for routing, business-tool workflows, safety controls, and live agent behavior.

## Executive summary

ShopAssist's saved live routing result is **110/110 (100%)**, up from the preserved **101/110 (91.8%)** baseline. The deterministic suite now exercises real tools, failure injection, and seeded SQLite workflows: **20/20 checks passed**. It exposed and verified fixes for return eligibility being based on purchase date, irrelevant policy snippets in return-window answers, and named-product stock lookups. The focused Python suite passes **20/20 tests** in isolated SQLite mode.

The expanded live end-to-end evaluation completed all **16** scenarios through Groq. After fixing the named-product availability tool guidance and rerunning that case, the assertion-based checks passed for tool selection (16/16), tool arguments (14/14 applicable cases), tool execution (15/15 applicable cases), final answers (16/16), and policy compliance (16/16). Customer-data isolation passed 3/3 cases; unauthorized-action rejection passed 2/2. These are small, synthetic, phrase-checked results—not production success rates or independent semantic reviews.

All local workflow checks used an isolated temporary SQLite database with synthetic seeded data. No production customer database was used.

## Routing regression comparison

| Measure | Preserved baseline | Latest saved run | Change |
|---|---:|---:|---:|
| Correct intent and route | 101/110 (91.8%) | 110/110 (100%) | +9 cases, +8.2 percentage points |
| General questions | 24/30 (80%) | 30/30 (100%) | +6 |
| Cancellation | 8/10 (80%) | 10/10 (100%) | +2 |
| Payment status | 9/10 (90%) | 10/10 (100%) | +1 |
| Other six intents | 60/60 (100%) | 60/60 (100%) | unchanged |

The detailed original and updated results are [`110-scenario-groq-before-phase1.json`](live_results/110-scenario-groq-before-phase1.json) and [`110-scenario-groq.json`](live_results/110-scenario-groq.json). This is a project-owned routing set; it is not an independent benchmark and does not assess tool execution or response correctness.

## Deterministic business workflow checks

The new [`workflow_checks.py`](workflow_checks.py) ran 20 checks against real ShopAssist tools and services, including tool and model failure injection.

| Dimension | Result |
|---|---:|
| Tool execution | 13/13 (100%) |
| Customer data isolation | 5/5 (100%) |
| Unauthorized action rejection | 2/2 (100%) |
| Approval and confirmation gates | 3/3 (100%) |
| Escalation ticket creation | 1/1 (100%) |
| Failure handling | 3/3 (100%) |
| Policy compliance | 6/6 (100%) |
| Overall checks | 20/20 (100%) |

### Regression fixes

`OrderService.can_return()` now evaluates the 14-day limit from the shipment's verified delivered event, not the order creation timestamp. It denies eligibility when the shipment, delivered event, or timestamp cannot be verified. A regression check confirms an order created 30 days ago but delivered recently is still within the return window, while a delivery older than 14 days is rejected.

The return policy document now uses the explicit phrase “return window,” and retrieval filters weakly related documents before formatting evidence. The return-window answer no longer includes an unrelated payments-policy excerpt. The product-search instructions now distinguish checking a named item's stock from searching for products that are in stock; a focused live rerun confirmed the agent finds the Laptop Sleeve and reports it as out of stock. The 10-question local RAG check scores Recall@1 **90%**, Recall@3 **100%**, MRR **0.95**, and all expected facts found in retrieved chunks.

The remaining checks verified product and inventory lookup, owned order and shipment access, policy source attribution, read-only payment lookup, guest authentication, cancellation request idempotency and customer confirmation, return customer confirmation and human approval, and support-ticket ownership.

Machine-readable case details are in [`workflow-checks.json`](live_results/workflow-checks.json).

## Live agent quality

The live suite in [`agent_quality.py`](agent_quality.py) covers 16 cases: product and inventory lookup, order lookup/listing, tracking, policy retrieval, payment status, cancellation, eligible and expired returns, escalation, guest access, cross-customer isolation, prompt injection, and unauthorized cancellation. It checks selected tools, arguments, tool results, answer requirements, and safety outcomes.

| Dimension | Result on 9 November 2026 |
|---|---|
| Cases scored | 16/16 |
| Tool selection | 16/16 (100%) |
| Tool arguments | 14/14 applicable cases (100%) |
| Tool execution through the LLM workflow | 15/15 applicable cases (100%) |
| Assertion-based final-answer checks | 16/16 (100%) |
| Policy compliance checks | 16/16 (100%) |
| Customer data isolation | 3/3 adversarial/guest cases passed |
| Unauthorized action rejection | 2/2 adversarial cases passed |
| Provider errors during completed run | None |

The first expanded run found a genuine out-of-stock lookup error: the agent filtered out the named product and said it could not find it. Tool guidance was corrected, and the scenario was rerun live and merged into the 16-case report. Guest responses that repeat an order ID supplied by the user are no longer treated as a privacy leak; punctuation variants are normalized, and the return evaluator accepts “the window has passed” as equivalent to “expired.” One guest scenario has no tool arguments or execution, so it is excluded from those denominators. Full results are in [`agent-quality-groq.json`](live_results/agent-quality-groq.json); the earlier 10-case baseline and pre-guidance run are preserved as [`agent-quality-groq-10-scenario-baseline.json`](live_results/agent-quality-groq-10-scenario-baseline.json) and [`agent-quality-groq-16-scenario-before-stock-guidance.json`](live_results/agent-quality-groq-16-scenario-before-stock-guidance.json).

## How to reproduce

From the repository root, using the project virtual environment:

```powershell
$env:PYTHONIOENCODING = 'utf-8'
.\.venv\Scripts\python.exe -m evaluation.workflow_checks
.\.venv\Scripts\python.exe -m evaluation.agent_quality
```

The first command is deterministic and does not require a model provider. The second requires a reachable, configured provider; it spaces requests out and retries a rate-limited case once. Use `--case-ids out_of_stock_product --output-path evaluation/live_results/focused.json` for a focused live rerun, then `--merge-from evaluation/live_results/focused.json` to merge it into the full report. Add `--rescore-existing` to rescore saved answers without another model call. Both suites use temporary seeded SQLite data and save JSON reports under `evaluation/live_results/`. To run the focused tests with SQLite instead of the `.env` PostgreSQL setting, initialize an isolated test database first and set `DATABASE_URL` to an empty string.

## What this baseline does and does not establish

- The 110-scenario report establishes routing accuracy for the saved Groq run.
- The deterministic suite establishes behavior for the measured database and business-tool checks.
- The live checks use hand-authored scenarios and phrase-based answer assertions; their perfect scores do not establish a real-world resolution rate or replace human review of answer quality.
- Scenario counts are small and synthetic. They do not establish real-world resolution rate, workload reduction, production reliability, or customer satisfaction.
- The return-window regression is fixed and included in the deterministic suite. The live agent now has an initial measured baseline; expand the scenario set and failure cases before making broader reliability claims.
