# ShopAssist support operations

## Business problem

Small e-commerce support teams spend time reading every incoming message, deciding which team should handle it, and determining which issue needs attention first. ShopAssist now creates a structured triage recommendation when a ticket is opened and puts that work into a human-controlled queue.

## Ticket workflow

1. A customer asks ShopAssist for help. If the agent cannot resolve the issue, it creates a support ticket.
2. The configured LLM receives a redacted excerpt and returns a category, priority, short summary, suggested team, evidence-based reason, and self-reported confidence.
3. The application records the suggestion with the original ticket. A model failure never blocks ticket creation; it marks the ticket for manual review.
4. A support manager reviews the original message and can change the queue category or priority. Those changes are recorded in the admin audit log, and the original AI recommendation remains visible.
5. A human updates ticket status. The AI does not close tickets, issue refunds, cancel orders, or make policy eligibility decisions.

## Queue measures

The admin dashboard reports the active backlog, high/urgent items, tickets requiring triage, open-ticket categories, return approvals, orders, and customers. These are operational counts from the local demonstration database; they are not customer-service ROI or production-performance claims.

The service-performance view also reports observed ticket and authenticated agent activity over an optional date range. It distinguishes staff pickup (an internal status change or note) from a customer-facing reply, measures resolution only after a human marks a ticket resolved, counts explicit feedback and reopened tickets, and labels tool failures and ticket-creating escalations. A customer selecting “helpful” is not treated as proof that their issue was resolved.

## Data and safety limits

- Ticket summaries are recommendations for staff, not final answers or actions.
- Agent turn telemetry records intent, outcome, tool names/success/duration, and total latency. It deliberately excludes message text and tool arguments.
- Email addresses, order references, phone-like numbers, and long numeric identifiers are removed from the ticket excerpt before the model call. The original message remains available to authorized admins in the database.
- AI priority and confidence have not been independently calibrated. A human remains responsible for queue priority and status.
- The demo database contains generated customers, orders, addresses, inventory, and tickets. Replace those records with authorized business data before operational use.
- Current local PostgreSQL and admin-key setup demonstrates the workflow; production deployment still needs individual staff identities, role-based permissions, and secret management.
