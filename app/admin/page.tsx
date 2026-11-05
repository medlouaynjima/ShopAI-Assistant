"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";

type Ticket = {
  ticket_id: string;
  customer_email: string;
  order_id: string | null;
  description: string;
  status: "open" | "in_progress" | "resolved";
  created_at: string;
};

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
  pending_return_approvals: number;
  recent_tickets: Ticket[];
};

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
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const loadData = useCallback(async () => {
    const [summary, ticketRows, returnRows, auditRows] = await Promise.all([
      requestJson<Dashboard>("/api/backend/admin/dashboard"),
      requestJson<Ticket[]>("/api/backend/admin/tickets"),
      requestJson<PendingReturn[]>("/api/backend/admin/returns/pending"),
      requestJson<AuditEvent[]>("/api/backend/admin/audit"),
    ]);
    setDashboard(summary);
    setTickets(ticketRows);
    setReturns(returnRows);
    setAuditEvents(auditRows);
  }, []);

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
        <Metric label="Returns awaiting approval" value={dashboard?.pending_return_approvals ?? 0} />
      </section>

      <section className="admin-section">
        <div className="section-heading">
          <div><span className="eyebrow">CUSTOMER CARE</span><h2>Support tickets</h2></div>
        </div>
        {tickets.length === 0 ? <p className="muted">No support tickets yet.</p> : (
          <div className="admin-list">
            {tickets.map((ticket) => (
              <article className="admin-card" key={ticket.ticket_id}>
                <div className="admin-card-top">
                  <strong>{ticket.ticket_id}</strong>
                  <span className={`admin-status ${ticket.status}`}>{ticket.status.replace("_", " ")}</span>
                </div>
                <p>{ticket.description}</p>
                <div className="admin-card-meta">
                  <span>{ticket.customer_email}</span>
                  <span>{ticket.order_id || "No linked order"}</span>
                  <time>{new Date(ticket.created_at).toLocaleString()}</time>
                </div>
                <label className="admin-status-control">
                  Update status
                  <select
                    value={ticket.status}
                    onChange={(event) => void updateTicket(ticket.ticket_id, event.target.value as Ticket["status"])}
                  >
                    <option value="open">Open</option>
                    <option value="in_progress">In progress</option>
                    <option value="resolved">Resolved</option>
                  </select>
                </label>
              </article>
            ))}
          </div>
        )}
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

function Metric({ label, value }: { label: string; value: number }) {
  return (
    <article className="admin-metric">
      <span>{label}</span>
      <strong>{value.toLocaleString()}</strong>
    </article>
  );
}
