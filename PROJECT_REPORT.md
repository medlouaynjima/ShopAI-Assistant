# ShopAssist Project Report

**Project:** Morrow Supply / ShopAssist AI  
**Report date:** 5 November 2026  
**Scope:** Current source code and local configuration. Secret values are intentionally excluded.

## 1. Executive summary

This repository is a customer support and e-commerce demo. It combines a public product storefront, customer accounts, an in-page support chatbot, a FastAPI backend, a LangGraph tool-using agent, PostgreSQL, Redis caching, optional pgvector retrieval, and optional LangSmith/Langfuse tracing.

The customer experience is now a public storefront rather than a login-only support page. Visitors can browse the catalog and ask public product or policy questions. Sign-in gates personal data such as orders, payments, and shipping details. The chat is a floating widget.

The project is **not yet a real, production e-commerce business**. The brand identity is a project placeholder, products and inventory are seeded demo records, delivery tracking is simulated, and there is no payment processor. Checkout records an unpaid demo order. It does not charge a card or reserve inventory.

The storefront name **Morrow Supply** and its SVG monogram are a custom project identity, not the user's verified business name, trademark, or final brand assets.

## 2. What a customer can do

### Browse the public shop

- Open the storefront without signing in.
- Search products and filter by category or availability.
- See catalog prices, descriptions, and inventory from the configured database.
- Add and remove products from a bag stored in the browser's local storage.
- Open the floating support chat from the shop.

The catalog currently contains 16 seeded products. Product photos are stock images for selected categories; other products use generated-in-code illustrations. The photos and descriptions do not establish that the items are real, purchasable supplier inventory.

### Create an account and sign in

- Register with name, email, and password.
- Verify the email before signing in.
- Use a signed-in session to access account-specific chat and order data.
- Sign out to revoke the session.

The backend implements registration, email verification, password hashing, expiring sessions, and logout. **SMTP is not configured in the current environment**, so the verification email cannot currently be delivered and new registrations will fail until SMTP is configured. Existing verified accounts can still sign in.

### Use the support assistant

- Visitors can ask public questions about products and published policies.
- Signed-in users can ask about their orders, deliveries, payment records, returns, and support requests.
- Customer conversations are stored by customer and chat session; the UI provides a clear-history action.
- When an order cancellation request does not include an ID, the backend looks up cancellable orders belonging to the signed-in customer. If there is one eligible order, it can create a pending request; if there are several, it asks which one.
- The assistant does not finalize a cancellation until the customer confirms it.

The assistant is designed to use catalog, order, shipment, policy, payment, return, and support tools. Responses depend on the selected model being available and the requested fact existing in the project data.

### Checkout

The bag opens a delivery form. The backend checks the requested SKU, current database price, and available quantity, then creates an order with status `awaiting_payment` and a payment record marked `not_configured`.

This is a **demo order flow**, not a paid purchase. It does not collect payment, reserve stock, send an order email, or book a shipment. The confirmation screen states that no charge was made.

## 3. AI agents and workflow

### Actual architecture

The active customer workflow is one controlled LangGraph, not five independent autonomous agents:

1. **Supervisor:** classifies intent and extracts order or tracking identifiers using the conversation context.
2. **Shared customer agent:** uses model function calling to select among the tools allowed for the request.
3. **Response node:** produces a customer-facing answer from tool evidence and handles safe fallbacks.

The older order, product, payment, returns, and support specialist modules remain in the repository for compatibility and focused development. They are not separate nodes in the active graph. The payment specialist is a small helper; the payment capability itself is read-only lookup of demo records.

The agent has a bounded tool loop and handles model/tool failures with offline intent and identifier fallbacks. The workflow injects the signed-in customer identity server-side so the model cannot choose another account's email for scoped tools.

### Available tools

| Tool area | What it can do now |
|---|---|
| Product search | Search catalog records and current demo inventory |
| Order lookup | Retrieve one order, list a customer's orders, or search that customer's orders |
| Cancellation | Find cancellable orders, create a pending cancellation request, then confirm it |
| Shipping | Read shipment and tracking events from local demo records |
| Returns | Check eligibility, create a return request, accept customer confirmation, and queue human approval |
| Payment | Read simulated payment status for an order owned by the signed-in customer |
| Policy retrieval | Retrieve policy excerpts and source paths from stored knowledge documents |
| Support | Create a support ticket for later human review |

These tools do not connect to a live carrier, payment gateway, refund service, or external ticketing platform.

### LLM configuration

The current local configuration selects **Groq** and has its provider credential configured. The code also supports Google Gemini, OpenAI, and local Ollama. The selected model is called through LangChain; the LLM provider is configurable through `.env`.

The API key that was pasted into the earlier conversation should be rotated. This report does not include the key.

## 4. Business workflows and current limits

### Orders and cancellation

- Orders are scoped to the signed-in customer.
- Checkout-created orders are marked `awaiting_payment` because payment is not connected.
- Confirmed and unpaid demo orders can enter the cancellation workflow.
- A cancellation request is stored as pending; confirmation changes the order status to cancelled.
- Shipped and delivered orders are not eligible for cancellation in the current workflow.

### Returns and refunds

- The written policy allows customers to initiate a return within 14 days of delivery, subject to item condition and exclusions.
- Return shipping is free for defective or wrong items; otherwise the buyer pays.
- A customer return request must be confirmed by the customer and then approved by an admin.
- Approval is recorded for the demo. **No money is refunded or transferred.**

### Shipping

Tracking numbers, carriers, statuses, and events are read from the local database. The policy file explicitly says these are demonstration records and may not reflect a live carrier service.

### Payments

Payment lookup is read-only. Checkout creates a placeholder payment record; there is no Stripe, Adyen, PayPal, or other payment integration, and no card details are collected.

### Support tickets and admin

- Customers can create a support ticket stored in PostgreSQL.
- `/admin` contains a dashboard for metrics, tickets, pending returns, and an audit log.
- Admin actions use a shared API key stored in an HttpOnly cookie, rather than a full user/role system.
- **No admin key is configured in the current environment**, so admin functions that require it are disabled until one is set.

## 5. Data and infrastructure

### PostgreSQL

PostgreSQL is the active local relational database. It stores customers, orders, products, shipments, payment records, returns, cancellations, support tickets, auth sessions, conversation messages, knowledge documents, and admin audit records. The schema is created during API startup. The repository also contains a non-destructive SQLite-to-PostgreSQL copy utility, and SQLite remains a fallback for development.

For this local setup, the existing SQLite records were copied to PostgreSQL; the original SQLite file was left unchanged.

Current local PostgreSQL row counts at the time of this report:

| Table | Rows |
|---|---:|
| Customers | 4 |
| Orders | 27 |
| Products | 16 |
| Shipments | 9 |
| Payment records | 27 |
| Returns | 3 |
| Cancellation requests | 1 |
| Support tickets | 0 |
| Auth session records | 10 |
| Conversation messages | 28 |
| Knowledge documents | 21 |
| Admin audit events | 30 |

Counts change as the app is used. Session rows include stored session history; they are not necessarily all active sessions.

### Redis

Redis is configured for a 60-second product search/cache layer. If Redis is unavailable, product reads fall back to the relational database. Redis is **not** currently used for authentication sessions or a background queue.

### pgvector and knowledge retrieval

The PostgreSQL `vector` extension and 768-dimensional embeddings are supported. Policy documents and active product records are synchronized, cleaned, and split into section-aware chunks. Retrieval combines keyword ranking with pgvector cosine ranking using reciprocal-rank fusion, then applies a deterministic relevance reranker. The configured database currently has **21 embedded chunks**. Gemini is used for embeddings only; Groq remains the chat and tool-calling provider.

### Current local runtime

- Storefront: `http://127.0.0.1:3000/`
- FastAPI: `http://127.0.0.1:8002/`
- PostgreSQL local port: `55432`
- Redis local port: `6379`

Port 8002 is the local development API port used by the storefront proxy and launcher. The Docker Compose API uses port 8000 inside its container network.

## 6. API and application structure

The API includes routes for health, registration and verification, login/profile/logout, public products/categories, checkout, personal orders, authenticated and guest chat, conversation history, cancellation, returns, support tickets, and admin operations.

The Next.js same-origin proxy forwards customer requests to FastAPI and stores the bearer session token in an HttpOnly cookie. The public catalog and guest chat do not require authentication; personal order and account routes do.

Key source files:

- `app/page.tsx` and `components/shop-assist-app.tsx` — storefront, account UI, order view, bag, checkout form, floating chat.
- `app/api/backend/[...path]/route.ts` — same-origin backend proxy and allowlist.
- `src/api/routes.py` and `src/api/schemas.py` — FastAPI endpoints and request/response types.
- `src/agent/graph.py`, `supervisor.py`, `tools.py`, `fallback.py` — agent workflow and tool use.
- `src/services/` — database, authentication, catalog, checkout, orders, shipping, payments, returns, support, and knowledge services.
- `knowledge/` — policy source documents.
- `evaluation/scenarios.json` — 110 intent and follow-up evaluation scenarios.

## 7. Observability, evaluation, and validation

LangSmith and Langfuse credentials are configured in the current environment. The tracing code records workflow node names, intent category, status, duration, and trace metadata. It is designed not to export customer messages, prompts, order IDs, email addresses, or tool payloads.

The repository has a pytest suite for services, agent tools, workflow, persistence, and PostgreSQL integration. It also has a live 110-scenario evaluation runner that calls the configured LLM; that run can take around 27 minutes and may incur provider usage.

**Reliability checks run 4 November 2026:**

- The full test suite passed in an isolated temporary SQLite database: **75 passed, 1 skipped**. The PostgreSQL integration test was skipped because `TEST_DATABASE_URL` was not configured. The test run did not touch the local PostgreSQL dataset.
- A disposable API end-to-end run passed public catalog access, private-order authentication, registration and verification (SMTP mocked), login, demo checkout, order history, account-based cancellation lookup and customer confirmation, return request/customer confirmation/admin approval, support-ticket creation, and admin dashboard metrics. The agent graph was stubbed for the cancellation request, so this verifies the API orchestration and database action, not the live LLM's tool choice.
- TypeScript checking and Python compilation passed.
- The live 110-scenario Groq evaluation completed at a 15-second request interval. The raw runner initially scored **92/110 (83.6%)** because it treated the new account-scoped database order-status fast path as a route failure whenever it correctly answered directly. The scoring rule was corrected and regression-tested; the architecture-aware result is **101/110 (91.8%)**. Order status is 10/10 under the corrected rule. Product search, return policy, return requests, shipping, and support escalation each scored 10/10; payment status 9/10; cancellations 8/10; general/unknown questions 24/30. The evaluation output and failed prompts are saved in `evaluation/live_results/110-scenario-groq.json`.
- Nine scenarios remain misrouted: two cancellation paraphrases (“stop the order” and “withdraw order”), one payment-status phrasing (“transaction status”), and six unsupported/general questions classified as product, return-policy, payment, or order questions. One model response was malformed JSON and used the supervisor's offline fallback; the run continued.
- The evaluation scorer now accepts a verified supervisor database fast path as a correct response route, instead of requiring every supported intent to enter the model tool loop. Future live runs can use `python -m evaluation.run --request-delay-seconds 15`.

**Phase 1 follow-up, 5 November 2026:**

- Fixed cancellation paraphrases such as “stop the order” and “withdraw order” using explicit order-action context, and preserved transaction/payment status intent when the classifier would otherwise choose order progress.
- Tightened the supervisor prompt and fallback so unsupported store services and delivery/refund guarantees are handled as general questions instead of being sent to unrelated agents.
- Added strict Groq JSON-schema output for the supervisor and hardened response parsing. The live runner now rejects offline fallbacks, retries transient failures, checkpoints each completed case, and resumes without delaying cached cases.
- The live Groq evaluation scored **110/110 (100%)**, compared with the corrected baseline of **101/110 (91.8%)**: **+9 cases / +8.2 percentage points**. General/unknown improved from 24/30 to 30/30 (+6), cancellation from 8/10 to 10/10 (+2), and payment status from 9/10 to 10/10 (+1). All other intents stayed at 10/10. There were no failed routing cases in the new run.
- The evaluation is **supervisor intent/routing only**. It does not measure tool selection/arguments, tool execution, final-answer quality, or policy compliance. It used an isolated, seeded SQLite database because the configured PostgreSQL service was unreachable; order fast paths were therefore tested against demo data, not the configured PostgreSQL instance.
- Baseline: `evaluation/live_results/110-scenario-groq-before-phase1.json`. Current result: `evaluation/live_results/110-scenario-groq.json`.
- The broader live agent-quality suite was attempted separately but stopped on a Groq `RateLimitError` during the cancellation case. No tool-quality percentages are claimed because the partial attempt did not persist scored case evidence. See [`evaluation/PHASE1_REPORT.md`](evaluation/PHASE1_REPORT.md) for the routing comparison, corrected baseline failures, and quality-evaluation status.
- The focused regression/evaluator/database-sanitization checks passed: **22 passed**. Python compilation and TypeScript checking passed. The full suite and PostgreSQL integration were not completed in this environment.

The earlier test run emitted deprecation warnings from FastAPI lifecycle hooks and the installed LangSmith library; they did not fail the suite.

## 8. What is complete, partial, and missing

### Phase 2 RAG progress (5 November 2026)

- Implemented markdown cleaning, section-aware chunking, a separate chunk table, batched 768-dimensional embedding indexing, hybrid keyword/vector retrieval, reciprocal-rank fusion, deterministic reranking, citation-preserving excerpts, and fallback to lexical retrieval when vector search is unavailable.
- Added a ten-question known-answer benchmark. Keyword fallback and PostgreSQL hybrid retrieval both scored **Recall@1 = 90%, Recall@3/5 = 100%, MRR = 0.95**, with the expected fact present in **10/10** results. The lowest-ranked case ranked the shipping policy first and the returns policy second.
- Benchmark outputs: `evaluation/live_results/rag-retrieval.json` (keyword fallback) and `evaluation/live_results/rag-retrieval-postgres.json` (Gemini query embeddings with pgvector). Run `python -m evaluation.rag_quality` or `python -m evaluation.rag_quality --postgres`.
- Generated and stored embeddings for **21 knowledge chunks** in PostgreSQL. The local Compose PostgreSQL service is running. Its existing role password was aligned to the already configured Compose credential without changing stored records. The 10-question vector-path run passed and matched the keyword baseline; expand the benchmark before claiming a general quality improvement.

### Phase 3 MCP progress (5 November 2026)

- Added the official MCP Python SDK v2 and a local stdio server at `src/mcp_server.py`.
- Exposed public product search and authenticated order lookup. The order tool accepts no customer identity input; it validates a ShopAssist session token, derives the owner from the session, and hides whether another customer's order exists.
- Added an official MCP SDK client smoke runner and synchronous isolated security checks. The security checks passed product search, missing/invalid session rejection, owner lookup, and cross-customer isolation. The asynchronous SDK client smoke did not complete in the current Windows Python runtime, so wire-level discovery/execution still needs a successful run.
- Architecture, host configuration, and limits are documented in `MCP_INTEGRATION.md`. The current stdio server is intended for one trusted local host process/customer session and is not a multi-user network MCP endpoint.

### Phase 4 security and reliability progress (5 November 2026)

- Replaced wildcard credentialed CORS with explicit configurable local origins; added per-IP limits for authentication, chat, and checkout endpoints.
- Added prompt-injection boundary instructions. Reviewed server-side ownership checks, customer confirmation, human return approval, and idempotent workflow operations.
- Seven focused tests passed. Full async API/agent validation and PostgreSQL-backed checks remain incomplete in this Windows environment. See `evaluation/PHASE4_SECURITY_REPORT.md` for scope and limits.

### Implemented

- Public product storefront and floating support chat.
- Account-scoped auth/session and customer order access.
- LangGraph intent routing and tool-driven domain workflow.
- PostgreSQL schema and local migrated data; Redis catalog caching.
- Demo orders, seeded shipping and payment records, policy lookup, tickets, return approval, and audit trail.
- Optional LangSmith/Langfuse traces.
- Local Docker Compose definitions for PostgreSQL/pgvector, Redis, API, and web.

### Partial or configured but not operational

- Account registration exists, but SMTP is unset so email verification cannot currently be delivered.
- PostgreSQL/pgvector is configured and contains 21 indexed knowledge chunks. Gemini generates embeddings; Groq handles chat and tool calls. The small retrieval benchmark measured Recall@3 100% and MRR 0.95, matching the keyword baseline.
- Admin interface exists and a local admin key is configured in the ignored `.env` file.
- Checkout creates a pending, unpaid demo order only.
- Morrow Supply is a placeholder identity, not a registered/verified business brand.
- Current catalog descriptions, prices, inventory, shipment events, and payment statuses are demo data.

### Required before accepting real customers or payments

1. Supply the real business name, logo/brand assets, catalog, product images, prices, stock source, and legal store policies.
2. Configure a payment provider and implement hosted checkout, payment webhooks, order/payment reconciliation, refunds, and failure handling.
3. Connect a real shipping/fulfillment provider and define shipping rates, taxes, delivery estimates, and tracking updates.
4. Configure SMTP or another verified email service for registration and order notifications.
5. Configure admin credentials and replace the shared-key admin gate with proper role-based staff authentication.
6. Keep the Gemini embedding index synchronized with policy and active catalog changes; expand retrieval evaluation with more paraphrases and ambiguous queries.
7. Keep the replacement Groq API key only in ignored environment files or a secret manager. Rotate the local PostgreSQL credential and update the database URL and Compose password together.
8. Configure a public deployment, Redis-backed rate limiting, persistent request/LLM monitoring, backups, privacy/retention controls, and end-to-end payment/security checks. Current rate limits and LLM metrics are process-local.

## 9. Overall assessment

ShopAssist now demonstrates the shape of an AI-supported e-commerce application: public shopping, customer accounts, tool-using support, database-backed workflows, observability, and an admin review path. It is suitable for local demonstration and workflow iteration. It should not yet be presented as a live shop or used to accept real orders, money, or production customer data.

### Phase 5 deployment and monitoring progress (5 November 2026)

- Added database readiness checks, Compose health dependencies, and a GitHub Actions full-stack smoke job.
- Added an admin-only LLM metrics endpoint for latency, token counts, and optional configured cost estimates. Groq is now the default provider in code and setup docs.
- Compose config validation and 10 focused tests passed. Local container startup is unverified because Docker Desktop is unavailable; tracing services initialized but external DNS prevented confirming trace delivery. No public hosting target is configured. See `evaluation/PHASE5_DEPLOYMENT_REPORT.md`.

### Phase 6 portfolio materials (5 November 2026)

- Rewrote the architecture diagram to match the current Groq, PostgreSQL/pgvector, Redis, and LangSmith/Langfuse setup.
- Added architecture, agent-workflow, and RAG diagrams; a measured-results/limitations overview; a four-minute demo outline; and CV/LinkedIn copy under `docs/`.
- Updated README setup, evaluation links, provider details, test instructions, and stale RAG claims. `npm run typecheck`, Compose config validation, SVG parsing, and portfolio-file checks passed.
- Current product screenshots and a recorded demonstration remain outstanding. Existing `images/demo-1.png` and `images/demo-2.png` are legacy screenshots and are explicitly marked as such; they should not be used to represent the current storefront.
