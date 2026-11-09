"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";

type TicketCategory = "orders" | "shipping" | "returns" | "payments" | "products" | "account" | "complaint" | "other";
type TicketPriority = "urgent" | "high" | "normal" | "low";

const ticketCategories: TicketCategory[] = ["orders", "shipping", "returns", "payments", "products", "account", "complaint", "other"];
const ticketPriorities: TicketPriority[] = ["urgent", "high", "normal", "low"];
const ticketTeams = ["Unassigned", "Order management", "Logistics", "Returns", "Billing", "Product support", "Account security", "Customer care"];

type Ticket = {
  ticket_id: string;
  customer_email: string;
  order_id: string | null;
  description: string;
  status: "open" | "in_progress" | "resolved";
  created_at: string;
  category: TicketCategory;
  priority: TicketPriority;
  ai_category: TicketCategory;
  ai_priority: TicketPriority;
  triage_summary: string;
  suggested_team: string;
  triage_reason: string;
  triage_confidence: number;
  triage_source: "ai" | "fallback" | "human_reviewed" | "untriaged";
  subcategory: string;
  suggested_next_action: string;
  assigned_team: string;
  first_staff_activity_at: string | null;
  resolved_at: string | null;
  reopened_count: number;
  notes: TicketNote[];
};

type TicketNote = { note_id: string; author: string; note: string; created_at: string };

type PendingReturn = {
  rma_number: string;
  order_id: string;
  reason: string;
  status: string;
  refund_amount: number;
  created_at: string;
  customer_email: string;
};

type Dashboard = {
  total_orders: number;
  total_customers: number;
  open_tickets: number;
  high_priority_tickets: number;
  untriaged_tickets: number;
  ticket_category_counts: Record<string, number>;
  pending_return_approvals: number;
  recent_tickets: Ticket[];
};
type Analytics = {
  ticket_count: number; ticket_by_category: Record<string, number>; ticket_by_priority: Record<string, number>;
  backlog: number; average_minutes_to_first_staff_activity: number | null; average_minutes_to_resolution: number | null;
  escalation_rate: number | null; escalated_turns: number; authenticated_agent_turns: number;
  tool_failure_rate: number | null; average_agent_latency_ms: number | null;
  customer_confirmed_helpful_rate: number | null; feedback_count: number; reopened_tickets: number;
  definitions: Record<string, string>;
};
type QualityCase = { turn_id: string; customer_email: string; intent: string; outcome: string; tool_failures: number; latency_ms: number; created_at: string; feedback: string | null; user_message: string | null; assistant_response: string | null };

type AuditEvent = {
  event_id: string;
  action: string;
  resource_id: string;
  details: Record<string, string>;
  created_at: string;
};

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: {
      ...(init?.body ? { "content-type": "application/json" } : {}),
      ...init?.headers,
    },
    cache: "no-store",
  });
  const payload = await response.json().catch(() => ({})) as T & { detail?: string };
  if (!response.ok) {
    throw new Error(payload.detail || `Request failed (${response.status}).`);
  }
  return payload;
}

export default function AdminPage() {
  const [authenticated, setAuthenticated] = useState<boolean | null>(null);
  const [key, setKey] = useState("");
  const [dashboard, setDashboard] = useState<Dashboard | null>(null);
  const [tickets, setTickets] = useState<Ticket[]>([]);
  const [returns, setReturns] = useState<PendingReturn[]>([]);
  const [auditEvents, setAuditEvents] = useState<AuditEvent[]>([]);
  const [analytics, setAnalytics] = useState<Analytics | null>(null);
  const [qualityCases, setQualityCases] = useState<QualityCase[]>([]);
  const [ticketFilters, setTicketFilters] = useState({ status: "", category: "", priority: "" });
  const [dateRange, setDateRange] = useState({ from: "", to: "" });
  const [noteDrafts, setNoteDrafts] = useState<Record<string, string>>({});
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const loadData = useCallback(async () => {
    const params = new URLSearchParams(Object.entries(ticketFilters).filter(([, value]) => value));
    const dateParams = new URLSearchParams();
    if (dateRange.from) dateParams.set("date_from", dateRange.from);
    if (dateRange.to) dateParams.set("date_to", dateRange.to);
    const [summary, ticketRows, returnRows, auditRows, metrics, qualityRows] = await Promise.all([
      requestJson<Dashboard>("/api/backend/admin/dashboard"),
      requestJson<Ticket[]>(`/api/backend/admin/tickets${params.size ? `?${params}` : ""}`),
      requestJson<PendingReturn[]>("/api/backend/admin/returns/pending"),
      requestJson<AuditEvent[]>("/api/backend/admin/audit"),
      requestJson<Analytics>(`/api/backend/admin/analytics${dateParams.size ? `?${dateParams}` : ""}`),
      requestJson<QualityCase[]>("/api/backend/admin/quality-queue"),
    ]);
    setDashboard(summary);
    setTickets(ticketRows);
    setReturns(returnRows);
    setAuditEvents(auditRows);
    setAnalytics(metrics);
    setQualityCases(qualityRows);
  }, [ticketFilters, dateRange]);

  useEffect(() => {
    let active = true;
    void requestJson<{ authenticated: boolean }>("/api/admin/session")
      .then(async (result) => {
        if (!active) return;
        setAuthenticated(result.authenticated);
        if (result.authenticated) await loadData();
      })
      .catch((reason: unknown) => {
        if (active) {
          setAuthenticated(false);
          setError(reason instanceof Error ? reason.message : "Could not load admin session.");
        }
      });
    return () => { active = false; };
  }, [loadData]);

  async function signIn(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setBusy(true);
    try {
      await requestJson("/api/admin/session", {
        method: "POST",
        body: JSON.stringify({ key }),
      });
      setKey("");
      setAuthenticated(true);
      await loadData();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Admin sign-in failed.");
    } finally {
      setBusy(false);
    }
  }

  async function signOut() {
    setError("");
    try {
      await requestJson("/api/admin/session", {
        method: "POST",
        body: JSON.stringify({ action: "logout" }),
      });
      setAuthenticated(false);
      setDashboard(null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Admin sign-out failed.");
    }
  }

  async function refresh() {
    setError("");
    setBusy(true);
    try {
      await loadData();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not refresh dashboard.");
    } finally {
      setBusy(false);
    }
  }

  async function updateTicket(ticketId: string, status: Ticket["status"]) {
    setError("");
    try {
      await requestJson(`/api/backend/admin/tickets/${encodeURIComponent(ticketId)}`, {
        method: "PATCH",
        body: JSON.stringify({ status }),
      });
      await loadData();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not update ticket.");
    }
  }

  async function updateTicketTriage(ticket: Ticket, category: TicketCategory, priority: TicketPriority) {
    setError("");
    setBusy(true);
    try {
      await requestJson(`/api/backend/admin/tickets/${encodeURIComponent(ticket.ticket_id)}/triage`, {
        method: "PATCH",
        body: JSON.stringify({ category, priority }),
      });
      await loadData();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not update ticket triage.");
    } finally {
      setBusy(false);
    }
  }

  async function rerunTicketTriage(ticketId: string) {
    setError("");
    setBusy(true);
    try {
      await requestJson(`/api/backend/admin/tickets/${encodeURIComponent(ticketId)}/triage`, { method: "POST" });
      await loadData();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not triage this ticket.");
    } finally {
      setBusy(false);
    }
  }

  async function assignTeam(ticketId: string, assigned_team: string) {
    try {
      await requestJson(`/api/backend/admin/tickets/${encodeURIComponent(ticketId)}/team`, { method: "PATCH", body: JSON.stringify({ assigned_team }) });
      await loadData();
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Could not assign ticket."); }
  }

  async function addInternalNote(ticketId: string) {
    const note = noteDrafts[ticketId]?.trim();
    if (!note) return;
    try {
      await requestJson(`/api/backend/admin/tickets/${encodeURIComponent(ticketId)}/notes`, { method: "POST", body: JSON.stringify({ note }) });
      setNoteDrafts((current) => ({ ...current, [ticketId]: "" }));
      await loadData();
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Could not add internal note."); }
  }

  async function reviewQuality(turnId: string, label: string) {
    try {
      await requestJson("/api/backend/admin/quality-reviews", { method: "POST", body: JSON.stringify({ turn_id: turnId, label }) });
      await loadData();
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Could not save review."); }
  }

  async function approveReturn(rmaNumber: string) {
    setError("");
    try {
      await requestJson(
        `/api/backend/admin/returns/${encodeURIComponent(rmaNumber)}/approve`,
        { method: "POST", body: JSON.stringify({}) },
      );
      await loadData();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not approve return.");
    }
  }

  if (authenticated === null) {
    return <main className="loading-screen">Loading admin access…</main>;
  }

  if (!authenticated) {
    return (
      <main className="site-shell admin-shell">
        <section className="admin-login">
          <a className="brand" href="/">ShopAssist admin</a>
          <h1>Operations dashboard</h1>
          <p>Sign in with the configured admin key. It is stored in an HttpOnly cookie.</p>
          {error && <div className="notice error" role="alert">{error}</div>}
          <form onSubmit={(event) => void signIn(event)}>
            <label htmlFor="admin-key">Admin key</label>
            <input
              id="admin-key"
              type="password"
              autoComplete="current-password"
              value={key}
              onChange={(event) => setKey(event.target.value)}
              required
            />
            <button className="button dark-button" disabled={busy}>Sign in</button>
          </form>
        </section>
      </main>
    );
  }

  return (
    <main className="site-shell admin-shell">
      <header className="admin-heading">
        <div>
          <span className="eyebrow">SHOPASSIST OPERATIONS</span>
          <h1>Admin dashboard</h1>
        </div>
        <div className="admin-actions">
          <a className="text-button" href="/">Storefront</a>
          <button className="text-button" onClick={() => void refresh()} disabled={busy}>
            Refresh
          </button>
          <button className="text-button" onClick={() => void signOut()}>Sign out</button>
        </div>
      </header>
      {error && <div className="notice error" role="alert">{error}</div>}

      <section className="admin-metrics" aria-label="Store metrics">
        <Metric label="Orders" value={dashboard?.total_orders ?? 0} />
        <Metric label="Customers" value={dashboard?.total_customers ?? 0} />
        <Metric label="Open tickets" value={dashboard?.open_tickets ?? 0} />
        <Metric label="High priority" value={dashboard?.high_priority_tickets ?? 0} />
        <Metric label="Awaiting triage" value={dashboard?.untriaged_tickets ?? 0} />
        <Metric label="Returns awaiting approval" value={dashboard?.pending_return_approvals ?? 0} />
      </section>

      <section className="admin-section">
        <div className="section-heading"><div><span className="eyebrow">MEASURED SUPPORT OPERATIONS</span><h2>Service performance</h2></div></div>
        <div className="admin-actions">
          <label>From <input type="date" value={dateRange.from} onChange={(event) => setDateRange((value) => ({ ...value, from: event.target.value }))} /></label>
          <label>To <input type="date" value={dateRange.to} onChange={(event) => setDateRange((value) => ({ ...value, to: event.target.value }))} /></label>
        </div>
        <div className="admin-metrics">
          <Metric label="Ticket backlog" value={analytics?.backlog ?? 0} />
          <Metric label="Agent turns" value={analytics?.authenticated_agent_turns ?? 0} />
          <Metric label="Escalations" value={analytics?.escalated_turns ?? 0} />
          <Metric label="Tickets reopened" value={analytics?.reopened_tickets ?? 0} />
          <Metric label="Avg. agent latency (ms)" value={analytics?.average_agent_latency_ms ?? 0} />
          <Metric label="Customer feedback" value={analytics?.feedback_count ?? 0} />
          <Metric label="Avg. staff pickup (min)" value={analytics?.average_minutes_to_first_staff_activity ?? "N/A"} />
          <Metric label="Avg. resolution (min)" value={analytics?.average_minutes_to_resolution ?? "N/A"} />
          <Metric label="Tool failure rate" value={analytics?.tool_failure_rate == null ? "N/A" : `${Math.round(analytics.tool_failure_rate * 100)}%`} />
        </div>
        <p className="muted">{analytics?.definitions.first_staff_activity} Helpful rate: {analytics?.customer_confirmed_helpful_rate == null ? "No feedback yet" : `${Math.round(analytics.customer_confirmed_helpful_rate * 100)}% (${analytics.feedback_count} responses)`}. Escalation rate: {analytics?.escalation_rate == null ? "No turns yet" : `${Math.round(analytics.escalation_rate * 100)}%`}. Median is not implied; time averages use recorded timestamps.</p>
      </section>

      <section className="ticket-volume-panel" aria-labelledby="ticket-volume-title">
        <div>
          <span className="eyebrow">ACTIVE BACKLOG</span>
          <h2 id="ticket-volume-title">What customers need help with</h2>
        </div>
        {Object.keys(dashboard?.ticket_category_counts ?? {}).length === 0 ? (
          <p className="muted">No open or in-progress tickets right now.</p>
        ) : (
          <div className="ticket-volume-list">
            {Object.entries(dashboard?.ticket_category_counts ?? {}).sort((a, b) => b[1] - a[1]).map(([category, count]) => (
              <div className="ticket-volume-item" key={category}>
                <span>{category}</span><strong>{count}</strong>
              </div>
            ))}
          </div>
        )}
      </section>

      <section className="admin-section">
        <div className="section-heading">
          <div><span className="eyebrow">CUSTOMER CARE</span><h2>Support tickets</h2></div>
        </div>
        <div className="admin-actions ticket-filters">
          <label>Status <select value={ticketFilters.status} onChange={(event) => setTicketFilters((value) => ({ ...value, status: event.target.value }))}><option value="">All</option>{["open", "in_progress", "resolved"].map((value) => <option key={value} value={value}>{value.replace("_", " ")}</option>)}</select></label>
          <label>Category <select value={ticketFilters.category} onChange={(event) => setTicketFilters((value) => ({ ...value, category: event.target.value }))}><option value="">All</option>{ticketCategories.map((value) => <option key={value}>{value}</option>)}</select></label>
          <label>Priority <select value={ticketFilters.priority} onChange={(event) => setTicketFilters((value) => ({ ...value, priority: event.target.value }))}><option value="">All</option>{ticketPriorities.map((value) => <option key={value}>{value}</option>)}</select></label>
        </div>
        {tickets.length === 0 ? <p className="muted">No support tickets yet.</p> : (
          <div className="admin-list">
            {tickets.map((ticket) => (
              <article className="admin-card ticket-card" key={ticket.ticket_id}>
                <div className="admin-card-top">
                  <strong>{ticket.ticket_id} · {ticket.order_id || "General request"}</strong>
                  <div className="ticket-badges">
                    <span className={`ticket-priority ${ticket.priority}`}>{ticket.priority} priority</span>
                    <span className={`admin-status ${ticket.status}`}>{ticket.status.replace("_", " ")}</span>
                  </div>
                </div>
                <div className="ticket-summary">
                  <span className="eyebrow">TRIAGE SUMMARY</span>
                  <p>{ticket.triage_summary || "This older ticket needs triage."}</p>
                </div>
                <details className="ticket-original-message">
                  <summary>Read original customer message</summary>
                  <p>{ticket.description}</p>
                </details>
                <div className="admin-card-meta">
                  <span>{ticket.customer_email}</span>
                  <time>{new Date(ticket.created_at).toLocaleString()}</time>
                </div>
                <div className="ticket-recommendation">
                  <span><strong>AI recommendation:</strong> {ticket.ai_category} · {ticket.ai_priority} priority</span>
                  <span><strong>Suggested team:</strong> {ticket.suggested_team}</span>
                  <span><strong>Subcategory:</strong> {ticket.subcategory || "—"}</span>
                  <span><strong>Suggested next step:</strong> {ticket.suggested_next_action || "Review customer request"}</span>
                  <span><strong>Confidence:</strong> {ticket.triage_source === "untriaged" ? "Not triaged" : `${Math.round(ticket.triage_confidence * 100)}%`}</span>
                  <p>{ticket.triage_reason}</p>
                  <small>{ticket.triage_source === "human_reviewed" ? "Human-reviewed queue values; original AI recommendation retained." : ticket.triage_source === "fallback" ? "AI unavailable. Review this ticket manually." : ticket.triage_source === "untriaged" ? "Run triage to receive a recommendation." : "AI suggestion only. A human owns the decision."}</small>
                </div>
                <div className="ticket-triage-controls">
                  <label>
                    Queue category
                    <select
                      aria-label={`Set ${ticket.ticket_id} category`}
                      value={ticket.category}
                      disabled={busy}
                      onChange={(event) => void updateTicketTriage(ticket, event.target.value as TicketCategory, ticket.priority)}
                    >
                      {ticketCategories.map((category) => <option key={category} value={category}>{category}</option>)}
                    </select>
                  </label>
                  <label>
                    Queue priority
                    <select
                      aria-label={`Set ${ticket.ticket_id} priority`}
                      value={ticket.priority}
                      disabled={busy}
                      onChange={(event) => void updateTicketTriage(ticket, ticket.category, event.target.value as TicketPriority)}
                    >
                      {ticketPriorities.map((priority) => <option key={priority} value={priority}>{priority}</option>)}
                    </select>
                  </label>
                  <button className="button triage-button" disabled={busy} onClick={() => void rerunTicketTriage(ticket.ticket_id)}>
                    {ticket.triage_source === "untriaged" ? "Run AI triage" : "Refresh AI suggestion"}
                  </button>
                </div>
                <label className="admin-status-control">
                  Update status
                  <select
                    value={ticket.status}
                    disabled={busy}
                    onChange={(event) => void updateTicket(ticket.ticket_id, event.target.value as Ticket["status"])}
                  >
                    <option value="open">Open</option>
                    <option value="in_progress">In progress</option>
                    <option value="resolved">Resolved</option>
                  </select>
                </label>
                <label className="admin-status-control">Assigned team
                  <select value={ticket.assigned_team || "Unassigned"} disabled={busy} onChange={(event) => void assignTeam(ticket.ticket_id, event.target.value)}>
                    {ticketTeams.map((team) => <option key={team}>{team}</option>)}
                  </select>
                </label>
                <div className="ticket-internal-notes">
                  <strong>Internal notes</strong>
                  {ticket.notes.map((note) => <p key={note.note_id}><small>{note.author} · {new Date(note.created_at).toLocaleString()}</small><br />{note.note}</p>)}
                  <textarea aria-label={`Internal note for ${ticket.ticket_id}`} maxLength={4000} value={noteDrafts[ticket.ticket_id] ?? ""} onChange={(event) => setNoteDrafts((current) => ({ ...current, [ticket.ticket_id]: event.target.value }))} placeholder="Add an internal note for the support team" />
                  <button className="button triage-button" onClick={() => void addInternalNote(ticket.ticket_id)}>Add note</button>
                </div>
              </article>
            ))}
          </div>
        )}
      </section>

      <section className="admin-section">
        <div className="section-heading"><div><span className="eyebrow">QUALITY REVIEW</span><h2>Agent turns to inspect</h2></div></div>
        {qualityCases.length === 0 ? <p className="muted">No flagged or negatively rated turns in this queue.</p> : <div className="admin-list">{qualityCases.map((item) => <article className="admin-card" key={item.turn_id}>
          <div className="admin-card-top"><strong>{item.intent} · {item.outcome}</strong><time>{new Date(item.created_at).toLocaleString()}</time></div>
          <p>{item.feedback ? `Customer feedback: ${item.feedback}` : "Automatically surfaced due to an error or unverified answer."} · {item.tool_failures} tool failures · {item.latency_ms} ms</p>
          {item.user_message && <p><strong>Customer:</strong> {item.user_message}</p>}
          {item.assistant_response && <p><strong>Agent:</strong> {item.assistant_response}</p>}
          <div className="ticket-triage-controls">{["incorrect_answer", "policy_issue", "tool_failure", "privacy", "unnecessary_escalation", "missed_escalation", "other"].map((label) => <button className="button triage-button" key={label} onClick={() => void reviewQuality(item.turn_id, label)}>{label.replaceAll("_", " ")}</button>)}</div>
        </article>)}</div>}
      </section>

      <section className="admin-section">
        <div className="section-heading">
          <div><span className="eyebrow">AUDIT TRAIL</span><h2>Recent admin actions</h2></div>
        </div>
        {auditEvents.length === 0 ? <p className="muted">No admin actions have been recorded.</p> : (
          <div className="admin-list">
            {auditEvents.map((event) => (
              <article className="admin-card admin-audit-row" key={event.event_id}>
                <strong>{event.action.replaceAll("_", " ")}</strong>
                <span>{event.resource_id}</span>
                <code>{JSON.stringify(event.details)}</code>
                <time>{new Date(event.created_at).toLocaleString()}</time>
              </article>
            ))}
          </div>
        )}
      </section>

      <section className="admin-section">
        <div className="section-heading">
          <div><span className="eyebrow">HUMAN REVIEW REQUIRED</span><h2>Return approvals</h2></div>
        </div>
        {returns.length === 0 ? <p className="muted">No returns are waiting for approval.</p> : (
          <div className="admin-list">
            {returns.map((item) => (
              <article className="admin-card" key={item.rma_number}>
                <div className="admin-card-top">
                  <strong>{item.rma_number} · {item.order_id}</strong>
                  <span className="admin-status pending">Pending approval</span>
                </div>
                <p>{item.reason.replaceAll("_", " ")} · proposed amount ${item.refund_amount.toFixed(2)}</p>
                <div className="admin-card-meta">
                  <span>{item.customer_email}</span>
                  <time>{new Date(item.created_at).toLocaleString()}</time>
                </div>
                <button
                  className="button dark-button"
                  onClick={() => void approveReturn(item.rma_number)}
                >
                  Approve return
                </button>
                <p className="muted">Approval is recorded for this demo; no money is transferred.</p>
              </article>
            ))}
          </div>
        )}
      </section>
    </main>
  );
}

function Metric({ label, value }: { label: string; value: number | string }) {
  return (
    <article className="admin-metric">
      <span>{label}</span>
      <strong>{value.toLocaleString()}</strong>
    </article>
  );
}
