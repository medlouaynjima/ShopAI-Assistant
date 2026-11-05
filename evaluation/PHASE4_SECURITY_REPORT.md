# Phase 4 — Security and reliability report

Date: 5 November 2026

## Implemented

- Replaced credentialed wildcard CORS with explicit frontend origins. Defaults allow the local web app at `localhost:3000` and `127.0.0.1:3000`; deployments can set `CORS_ALLOWED_ORIGINS` to a JSON list.
- Added per-IP sliding-window request limits for login (8/5 min), registration (5/hour), email verification (10/15 min), authenticated chat (25/min), guest chat (15/min), and checkout (12/min). Blocked requests receive HTTP 429 and `Retry-After`.
- Added explicit prompt-injection boundaries to the customer agent instructions. Enforcement for private data and sensitive actions remains in server-controlled identity and service authorization checks.
- Reviewed customer scoping, cancellation/return confirmation, human approval, and repeat requests. Operations services verify order ownership, require customer confirmation before cancellation, require customer confirmation plus admin approval for returns, and make pending/confirmed repeat operations idempotent.

## Verification

Focused tests passed: 7 tests covering rate-limit windows and isolation, explicit CORS configuration, cancellation ownership and repeat confirmation, and return confirmation/approval.

The larger mixed API/agent test selection was not completed because an async test stalled in the local Windows Python runtime. PostgreSQL was unavailable to the first test invocation; rerunning against the configured SQLite test database allowed the synchronous checks to pass. No live model or production customer data was used.

## Limits and deployment notes

- Rate-limit counters are in process memory. They reset on restart and do not coordinate across workers or machines; use Redis-backed limits before scaling out.
- IP identification uses the socket peer and intentionally ignores forwarded headers. Configure a trusted proxy strategy before relying on client IP limits behind a reverse proxy.
- The limits are protective demo defaults, not load-tested production values. Tune them against expected traffic and add alerting.
- Prompt instructions are not a security boundary by themselves. Authorization remains in the API and service layer and needs adversarial API integration tests in CI.
- The separate MCP SDK client smoke and complete async API suite remain unverified in this environment.

## Required follow-up

- Revoke and replace the Groq API key previously pasted into the chat; treat that credential as exposed. Store the replacement only in the ignored `.env` file or a secret manager.
- Add Redis-backed rate limiting, reverse-proxy trust configuration, and CI runs against PostgreSQL.
- Complete adversarial prompt injection, API-level cross-customer access, unauthorized cancellation/return, model timeout, and rate-limit response tests in a working async test runtime.
