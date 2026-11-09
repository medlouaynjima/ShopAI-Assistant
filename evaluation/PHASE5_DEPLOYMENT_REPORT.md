# Phase 5 — Deployment and monitoring report

Date: 9 November 2026 (updated)

## Implemented

- Added database-aware `/api/v1/ready`. It returns 503 when the primary database is unavailable and reports Redis as healthy, degraded, or not configured. Redis remains optional because catalog reads fall back to the database.
- Updated Compose to wait for healthy PostgreSQL and Redis before starting the API, then wait for a healthy API before starting the web app. API and web containers now have health checks.
- Added a GitHub Actions Compose smoke job. It builds and starts the full stack, waits for API readiness and a web response, prints service status on success, and tears down its temporary volumes. CI also validates Compose configuration.
- Added privacy-safe aggregate LLM metrics at admin-protected `GET /api/v1/admin/llm-metrics`: call/error counts, average latency, provider/model, provider-reported token totals, and cost estimates only when per-model input/output rates are supplied.
- Aligned the app and setup documentation default chat provider with the user's selected Groq provider.
- Captured a brand-consistent promotional reel in `videos/shopassist-ai-promo-reel.mp4` and `.webm`; README links to both formats.

## Verification

- `docker compose config --quiet`: passed.
- Focused security, metrics, provider configuration, cancellation, and return checks: **10 passed**.
- Python compile check for changed backend modules: passed.
- The running local storefront and API were verified at `127.0.0.1:3000` and `127.0.0.1:8002`: storefront HTTP 200, API `/health` HTTP 200, API `/ready` HTTP 200 with database `ok` and optional cache `degraded`.
- `docker compose config --quiet`: passed. Docker daemon access was denied in the current environment, so full local Compose startup could not be verified. The CI smoke workflow is configured, but its hosted run has not happened yet.
- `npm run typecheck` and `npm run build`: passed. Python compilation passed. The local Python suite passed 102 tests with one skip; one API workflow test was deselected because its Windows TestClient portal stalled before the first request. PostgreSQL integration and the SDK's async MCP client smoke were not verified locally. Synchronous MCP authorization checks passed.
- A synthetic trace containing no customer content was attempted. Both tracing clients initialized, but LangSmith and Langfuse endpoints could not resolve because external DNS/network access is unavailable here; delivery was not verified.

## Operational limits and follow-up

- Metrics are in process memory and reset on restart. Multi-worker deployments need a shared metrics store. Provider billing remains authoritative.
- Cost values are not configured by default. Set `LLM_INPUT_COST_PER_1M_USD` and `LLM_OUTPUT_COST_PER_1M_USD` for the exact selected model; estimates are marked incomplete when responses omit token usage.
- No public deployment was created: this workspace has no chosen hosting target or deployment credentials. The Docker stack is configured for reproducible local/CI use and binds to loopback by default.
- Fresh storefront/admin screenshots were not captured: local browser-control capability is disabled in the current Work settings, and the connected Chrome handoff failed the browser-origin safety check. The existing reel is available, but it does not substitute for clean, current screenshots.
- With Docker Desktop available, run `docker compose up --build` and confirm `/api/v1/ready` and the storefront. Before a public demo, configure hosting, production secrets, database backups, shared rate limiting, and external monitoring.
