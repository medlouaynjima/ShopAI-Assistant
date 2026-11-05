# ShopAssist AI — 4-minute demo script

## Before recording

- Start PostgreSQL/Redis and the API/web app; verify the storefront, sign-in, admin page, and `/api/v1/ready`.
- Use only seeded demo accounts and orders. Hide browser autofill, API keys, email inboxes, admin secrets, and local `.env` files.
- If the model provider is rate-limited, use the recorded evaluation artifacts and say the live model call is unavailable; do not present a scripted result as a live response.

## Run of show

**0:00–0:20 — What this is**

“This is ShopAssist, a portfolio e-commerce demo with a database-backed support agent. The agent can search the catalog and policies, look up the signed-in customer's orders, and guide cancellation and return workflows.”

**0:20–0:55 — Storefront**

Show the public catalog and product search, add one demo product to the bag, and open the floating support bubble. Point out that browsing is public while account-specific data requires sign-in.

**0:55–1:35 — Agent uses data**

Ask: “Is the Mechanical Keyboard in stock, and what are its price and key features?” Show the live catalog tool evidence and concise response. Then ask a policy question such as “How long do I have to return an item?” and point out the cited policy source.

**1:35–2:15 — Account-scoped lookup**

Sign in with a seeded demo account and ask: “Show my recent orders.” Ask a follow-up about one order. Explain that the server derives account identity from the session and the tool cannot change the customer email supplied by the model.

**2:15–2:55 — Safe action workflow**

Request cancellation of a confirmed demo order. Show the pending request and the explicit confirmation step. Confirm it only if using a disposable demo order. Explain that return requests separately require customer confirmation and staff approval; neither path issues a real refund.

**2:55–3:25 — Architecture and observability**

Show the workflow diagram and the redacted tracing dashboard if external trace delivery is available. Show `/api/v1/admin/llm-metrics` only from an authorized admin session, and explain that token counts depend on provider metadata and cost estimates require configured model rates.

**3:25–4:00 — Evidence and limits**

Show the 110-case routing comparison (91.8% baseline to 100%) and 10-question RAG retrieval results (Recall@3 100%). State plainly that end-to-end LLM answer quality remains inconclusive and that payments, shipping, and current catalog/orders are demo integrations/data.
