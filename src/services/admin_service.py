"""Admin-only operational queues, analytics, and audit records."""
import json
import uuid
from datetime import datetime, time

from src.services.database import get_connection
from src.services.ticket_triage import triage_ticket

ALLOWED_TICKET_STATUSES = {"open", "in_progress", "resolved"}
ALLOWED_TICKET_CATEGORIES = {"orders", "shipping", "returns", "payments", "products", "account", "complaint", "other"}
ALLOWED_TICKET_PRIORITIES = {"urgent", "high", "normal", "low"}
ALLOWED_TICKET_TEAMS = {"Order management", "Logistics", "Returns", "Billing", "Product support", "Account security", "Customer care", "Unassigned"}
TICKET_FIELDS = "ticket_id, customer_email, order_id, description, status, created_at, category, priority, ai_category, ai_priority, triage_summary, suggested_team, triage_reason, triage_confidence, triage_source, subcategory, suggested_next_action, assigned_team, first_staff_activity_at, resolved_at, reopened_count"


class AdminService:
    def analytics(self, date_from: str | None = None, date_to: str | None = None) -> dict:
        def as_bound(value: str | None, end: bool = False) -> str | None:
            if not value:
                return None
            parsed = datetime.strptime(value, "%Y-%m-%d")
            return datetime.combine(parsed.date(), time.max if end else time.min).isoformat()
        lower, upper = as_bound(date_from), as_bound(date_to, True)
        conn = get_connection()
        try:
            clauses, params = [], []
            if lower:
                clauses.append("created_at >= ?"); params.append(lower)
            if upper:
                clauses.append("created_at <= ?"); params.append(upper)
            where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
            tickets = [dict(row) for row in conn.execute(
                f"SELECT category, priority, status, created_at, first_staff_activity_at, resolved_at, reopened_count FROM support_tickets{where}", params
            ).fetchall()]
            turns = [dict(row) for row in conn.execute(
                f"SELECT turn_id, outcome, tool_count, tool_failures, latency_ms, created_at FROM customer_agent_turns{where}", params
            ).fetchall()]
            feedback_where, feedback_params = where, list(params)
            feedback = conn.execute(
                f"SELECT f.feedback FROM conversation_feedback f JOIN customer_agent_turns t ON t.turn_id=f.turn_id{(' WHERE ' + ' AND '.join('t.' + c.split(' ', 1)[0] + ' ' + c.split(' ', 1)[1] for c in clauses)) if clauses else ''}", feedback_params
            ).fetchall()
            def average_minutes(values: list[float]) -> float | None:
                return round(sum(values) / len(values), 1) if values else None
            first_response, resolution = [], []
            for row in tickets:
                try:
                    created = datetime.fromisoformat(row["created_at"])
                    if row["first_staff_activity_at"]:
                        first_response.append((datetime.fromisoformat(row["first_staff_activity_at"]) - created).total_seconds() / 60)
                    if row["resolved_at"]:
                        resolution.append((datetime.fromisoformat(row["resolved_at"]) - created).total_seconds() / 60)
                except (ValueError, TypeError):
                    continue
            by_category, by_priority = {}, {}
            for row in tickets:
                by_category[row["category"]] = by_category.get(row["category"], 0) + 1
                by_priority[row["priority"]] = by_priority.get(row["priority"], 0) + 1
            explicit_feedback = [row["feedback"] for row in feedback]
            ticket_turns = sum(row["outcome"] == "escalated" for row in turns)
            return {
                "ticket_count": len(tickets), "ticket_by_category": by_category, "ticket_by_priority": by_priority,
                "backlog": sum(row["status"] != "resolved" for row in tickets),
                "average_minutes_to_first_staff_activity": average_minutes(first_response),
                "average_minutes_to_resolution": average_minutes(resolution),
                "escalation_rate": round(ticket_turns / len(turns), 4) if turns else None,
                "escalated_turns": ticket_turns, "authenticated_agent_turns": len(turns),
                "tool_failure_rate": round(sum(row["tool_failures"] for row in turns) / max(1, sum(row["tool_count"] for row in turns)), 4) if turns else None,
                "average_agent_latency_ms": round(sum(row["latency_ms"] for row in turns) / len(turns)) if turns else None,
                "customer_confirmed_helpful_rate": round(explicit_feedback.count("helpful") / len(explicit_feedback), 4) if explicit_feedback else None,
                "feedback_count": len(explicit_feedback), "reopened_tickets": sum(row["reopened_count"] for row in tickets),
                "definitions": {"first_staff_activity": "Ticket moved to in progress or internal note added; not a customer-facing reply.", "escalation_rate": "Ticket-creating agent turns divided by authenticated agent turns.", "resolution": "Tickets explicitly marked resolved by an operator.", "helpful_rate": "Explicit helpful customer feedback divided by all submitted feedback."},
            }
        finally:
            conn.close()

    def quality_queue(self, limit: int = 100) -> list[dict]:
        conn = get_connection()
        try:
            rows = conn.execute("""SELECT t.turn_id, t.customer_email, t.intent, t.outcome, t.tool_failures,
                    t.latency_ms, t.created_at, f.feedback,
                    (SELECT m.content FROM conversation_messages m WHERE m.turn_id=t.turn_id AND m.role='user' ORDER BY m.created_at LIMIT 1) AS user_message,
                    (SELECT m.content FROM conversation_messages m WHERE m.turn_id=t.turn_id AND m.role='assistant' ORDER BY m.created_at DESC LIMIT 1) AS assistant_response
                FROM customer_agent_turns t LEFT JOIN conversation_feedback f ON f.turn_id=t.turn_id
                WHERE (t.outcome IN ('tool_error','model_error','unverified_answer') OR f.feedback IN ('not_helpful','unresolved'))
                  AND NOT EXISTS (SELECT 1 FROM quality_reviews q WHERE q.turn_id=t.turn_id)
                ORDER BY t.created_at DESC LIMIT ?""", (max(1, min(limit, 200)),)).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    def add_quality_review(self, turn_id: str, reviewer: str, label: str, note: str = "") -> dict:
        review = {"review_id": uuid.uuid4().hex, "turn_id": turn_id, "reviewer": reviewer[:254], "label": label, "note": note.strip(), "created_at": datetime.now().isoformat()}
        conn = get_connection()
        try:
            if not conn.execute("SELECT 1 FROM customer_agent_turns WHERE turn_id = ?", (turn_id,)).fetchone():
                raise LookupError("Agent turn was not found.")
            conn.execute("INSERT INTO quality_reviews (review_id, turn_id, reviewer, label, note, created_at) VALUES (?, ?, ?, ?, ?, ?)", tuple(review.values()))
            self._audit(conn, "agent_turn_reviewed", turn_id, {"review_id": review["review_id"], "label": label})
            conn.commit()
            return review
        finally:
            conn.close()

    def list_tickets(
        self, status: str | None = None, category: str | None = None,
        priority: str | None = None, limit: int = 100,
    ) -> list[dict]:
        if status and status not in ALLOWED_TICKET_STATUSES:
            raise ValueError("Unsupported ticket status.")
        if category and category not in ALLOWED_TICKET_CATEGORIES:
            raise ValueError("Unsupported ticket category.")
        if priority and priority not in ALLOWED_TICKET_PRIORITIES:
            raise ValueError("Unsupported ticket priority.")
        safe_limit = max(1, min(limit, 200))
        filters = []
        params = []
        for column, value in (("status", status), ("category", category), ("priority", priority)):
            if value:
                filters.append(f"{column} = ?")
                params.append(value)
        conn = get_connection()
        try:
            where_sql = f" WHERE {' AND '.join(filters)}" if filters else ""
            rows = conn.execute(
                f"""SELECT {TICKET_FIELDS} FROM support_tickets{where_sql}
                   ORDER BY CASE priority WHEN 'urgent' THEN 0 WHEN 'high' THEN 1
                            WHEN 'normal' THEN 2 ELSE 3 END, created_at ASC LIMIT ?""",
                (*params, safe_limit),
            ).fetchall()
            tickets = [dict(row) for row in rows]
            if tickets:
                ids = [ticket["ticket_id"] for ticket in tickets]
                placeholders = ", ".join("?" for _ in ids)
                notes = conn.execute(
                    f"""SELECT note_id, ticket_id, author, note, created_at
                       FROM support_ticket_notes WHERE ticket_id IN ({placeholders})
                       ORDER BY created_at ASC""",
                    ids,
                ).fetchall()
                by_ticket: dict[str, list[dict]] = {ticket_id: [] for ticket_id in ids}
                for note in notes:
                    by_ticket[note["ticket_id"]].append(dict(note))
                for ticket in tickets:
                    ticket["notes"] = by_ticket[ticket["ticket_id"]]
            return tickets
        finally:
            conn.close()

    def pending_returns(self, limit: int = 100) -> list[dict]:
        safe_limit = max(1, min(limit, 200))
        conn = get_connection()
        try:
            rows = conn.execute(
                """SELECT r.rma_number, r.order_id, r.reason, r.status,
                          r.refund_amount, r.created_at, o.email AS customer_email
                   FROM returns r JOIN orders o ON o.order_id = r.order_id
                   WHERE r.status = 'pending_approval'
                   ORDER BY r.created_at ASC LIMIT ?""",
                (safe_limit,),
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    def recent_audit(self, limit: int = 100) -> list[dict]:
        safe_limit = max(1, min(limit, 200))
        conn = get_connection()
        try:
            rows = conn.execute(
                """SELECT event_id, action, resource_id, details, created_at
                   FROM admin_audit_log ORDER BY created_at DESC LIMIT ?""",
                (safe_limit,),
            ).fetchall()
            return [
                {
                    **dict(row),
                    "details": json.loads(row["details"]),
                }
                for row in rows
            ]
        finally:
            conn.close()

    def dashboard(self) -> dict:
        conn = get_connection()
        try:
            total_orders = conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
            total_customers = conn.execute("SELECT COUNT(*) FROM customers").fetchone()[0]
            open_tickets = conn.execute(
                "SELECT COUNT(*) FROM support_tickets WHERE status IN ('open', 'in_progress')"
            ).fetchone()[0]
            high_priority_tickets = conn.execute(
                """SELECT COUNT(*) FROM support_tickets
                   WHERE status IN ('open', 'in_progress') AND priority IN ('urgent', 'high')"""
            ).fetchone()[0]
            untriaged_tickets = conn.execute(
                """SELECT COUNT(*) FROM support_tickets
                   WHERE status IN ('open', 'in_progress') AND triage_source IN ('untriaged', 'fallback')"""
            ).fetchone()[0]
            category_counts = {
                row["category"]: row["total"]
                for row in conn.execute(
                    """SELECT CASE WHEN triage_source IN ('untriaged', 'fallback')
                                      THEN 'untriaged' ELSE category END AS category,
                              COUNT(*) AS total FROM support_tickets
                       WHERE status IN ('open', 'in_progress')
                       GROUP BY CASE WHEN triage_source IN ('untriaged', 'fallback')
                                     THEN 'untriaged' ELSE category END"""
                ).fetchall()
            }
            pending_returns = conn.execute(
                "SELECT COUNT(*) FROM returns WHERE status = 'pending_approval'"
            ).fetchone()[0]
            recent = conn.execute(
                f"""SELECT {TICKET_FIELDS} FROM support_tickets
                   ORDER BY CASE priority WHEN 'urgent' THEN 0 WHEN 'high' THEN 1
                            WHEN 'normal' THEN 2 ELSE 3 END, created_at ASC LIMIT 10"""
            ).fetchall()
            return {
                "total_orders": total_orders,
                "total_customers": total_customers,
                "open_tickets": open_tickets,
                "high_priority_tickets": high_priority_tickets,
                "untriaged_tickets": untriaged_tickets,
                "ticket_category_counts": category_counts,
                "pending_return_approvals": pending_returns,
                "recent_tickets": [dict(row) for row in recent],
            }
        finally:
            conn.close()

    def update_ticket(self, ticket_id: str, status: str) -> dict:
        if status not in ALLOWED_TICKET_STATUSES:
            raise ValueError("Unsupported ticket status.")
        conn = get_connection()
        try:
            conn.execute("BEGIN IMMEDIATE")
            ticket = conn.execute(
                "SELECT * FROM support_tickets WHERE ticket_id = ?",
                (ticket_id.strip().upper(),),
            ).fetchone()
            if ticket is None:
                raise LookupError(f"Support ticket {ticket_id} was not found.")
            if ticket["status"] != status:
                now = datetime.now().isoformat()
                reopened = int(ticket["reopened_count"] or 0) + int(ticket["status"] == "resolved" and status != "resolved")
                first_activity = ticket["first_staff_activity_at"]
                resolved_at = ticket["resolved_at"]
                if status == "in_progress" and not first_activity:
                    first_activity = now
                if status == "resolved":
                    resolved_at = now
                elif ticket["status"] == "resolved":
                    resolved_at = None
                conn.execute(
                    """UPDATE support_tickets SET status = ?, first_staff_activity_at = ?,
                       resolved_at = ?, reopened_count = ? WHERE ticket_id = ?""",
                    (status, first_activity, resolved_at, reopened, ticket["ticket_id"]),
                )
                self._audit(
                    conn,
                    "ticket_status_updated",
                    ticket["ticket_id"],
                    {"from": ticket["status"], "to": status},
                )
            conn.commit()
            result = dict(ticket)
            result["status"] = status
            result["first_staff_activity_at"] = first_activity if ticket["status"] != status else ticket["first_staff_activity_at"]
            result["resolved_at"] = resolved_at if ticket["status"] != status else ticket["resolved_at"]
            result["reopened_count"] = reopened if ticket["status"] != status else ticket["reopened_count"]
            return result
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def update_ticket_triage(self, ticket_id: str, category: str, priority: str) -> dict:
        if category not in ALLOWED_TICKET_CATEGORIES:
            raise ValueError("Unsupported ticket category.")
        if priority not in ALLOWED_TICKET_PRIORITIES:
            raise ValueError("Unsupported ticket priority.")
        conn = get_connection()
        try:
            conn.execute("BEGIN IMMEDIATE")
            ticket = conn.execute(
                "SELECT * FROM support_tickets WHERE ticket_id = ?",
                (ticket_id.strip().upper(),),
            ).fetchone()
            if ticket is None:
                raise LookupError(f"Support ticket {ticket_id} was not found.")
            before = {"category": ticket["category"], "priority": ticket["priority"]}
            after = {"category": category, "priority": priority}
            conn.execute(
                """UPDATE support_tickets SET category = ?, priority = ?, triage_source = 'human_reviewed'
                   WHERE ticket_id = ?""",
                (category, priority, ticket["ticket_id"]),
            )
            self._audit(conn, "ticket_triage_overridden", ticket["ticket_id"], {"from": before, "to": after})
            conn.commit()
            updated = conn.execute(
                f"SELECT {TICKET_FIELDS} FROM support_tickets WHERE ticket_id = ?",
                (ticket["ticket_id"],),
            ).fetchone()
            return dict(updated)
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def assign_ticket(self, ticket_id: str, team: str) -> dict:
        if team not in ALLOWED_TICKET_TEAMS:
            raise ValueError("Unsupported support team.")
        assigned_team = "" if team == "Unassigned" else team
        conn = get_connection()
        try:
            conn.execute("BEGIN IMMEDIATE")
            ticket = conn.execute(
                "SELECT ticket_id, assigned_team FROM support_tickets WHERE ticket_id = ?",
                (ticket_id.strip().upper(),),
            ).fetchone()
            if ticket is None:
                raise LookupError(f"Support ticket {ticket_id} was not found.")
            conn.execute(
                "UPDATE support_tickets SET assigned_team = ? WHERE ticket_id = ?",
                (assigned_team, ticket["ticket_id"]),
            )
            self._audit(conn, "ticket_team_assigned", ticket["ticket_id"],
                        {"from": ticket["assigned_team"], "to": assigned_team})
            conn.commit()
            return dict(conn.execute(
                f"SELECT {TICKET_FIELDS} FROM support_tickets WHERE ticket_id = ?",
                (ticket["ticket_id"],),
            ).fetchone())
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def add_ticket_note(self, ticket_id: str, note: str, author: str = "Admin") -> dict:
        content = note.strip()
        if not content:
            raise ValueError("Internal note cannot be empty.")
        if len(content) > 4000:
            raise ValueError("Internal note cannot exceed 4000 characters.")
        note_row = {
            "note_id": uuid.uuid4().hex,
            "ticket_id": ticket_id.strip().upper(),
            "author": author[:80],
            "note": content,
            "created_at": datetime.now().isoformat(),
        }
        conn = get_connection()
        try:
            conn.execute("BEGIN IMMEDIATE")
            if not conn.execute(
                "SELECT 1 FROM support_tickets WHERE ticket_id = ?", (note_row["ticket_id"],)
            ).fetchone():
                raise LookupError(f"Support ticket {ticket_id} was not found.")
            conn.execute(
                """INSERT INTO support_ticket_notes (note_id, ticket_id, author, note, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                tuple(note_row.values()),
            )
            conn.execute(
                """UPDATE support_tickets SET first_staff_activity_at = COALESCE(first_staff_activity_at, ?)
                   WHERE ticket_id = ?""",
                (note_row["created_at"], note_row["ticket_id"]),
            )
            self._audit(conn, "ticket_internal_note_added", note_row["ticket_id"],
                        {"note_id": note_row["note_id"]})
            conn.commit()
            return note_row
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def rerun_ticket_triage(self, ticket_id: str) -> dict:
        conn = get_connection()
        try:
            ticket = conn.execute(
                "SELECT ticket_id, description, triage_source FROM support_tickets WHERE ticket_id = ?",
                (ticket_id.strip().upper(),),
            ).fetchone()
            if ticket is None:
                raise LookupError(f"Support ticket {ticket_id} was not found.")
            ticket_id = ticket["ticket_id"]
            preserve_human_values = ticket["triage_source"] == "human_reviewed"
            description = ticket["description"]
        finally:
            conn.close()

        triage = triage_ticket(description)
        conn = get_connection()
        try:
            conn.execute("BEGIN IMMEDIATE")
            if preserve_human_values:
                conn.execute(
                    """UPDATE support_tickets SET ai_category = ?, ai_priority = ?,
                       subcategory = ?, triage_summary = ?, suggested_team = ?, triage_reason = ?,
                       suggested_next_action = ?, triage_confidence = ? WHERE ticket_id = ?""",
                    (triage["ai_category"], triage["ai_priority"], triage["subcategory"],
                     triage["triage_summary"], triage["suggested_team"], triage["triage_reason"],
                     triage["suggested_next_action"], triage["triage_confidence"], ticket_id),
                )
            else:
                conn.execute(
                    """UPDATE support_tickets SET category = ?, priority = ?, ai_category = ?,
                       ai_priority = ?, subcategory = ?, triage_summary = ?, suggested_team = ?,
                       triage_reason = ?, suggested_next_action = ?, triage_confidence = ?,
                       triage_source = ? WHERE ticket_id = ?""",
                    (triage["category"], triage["priority"], triage["ai_category"], triage["ai_priority"],
                     triage["subcategory"], triage["triage_summary"], triage["suggested_team"],
                     triage["triage_reason"], triage["suggested_next_action"], triage["triage_confidence"],
                     triage["triage_source"], ticket_id),
                )
            self._audit(
                conn, "ticket_ai_triage_run", ticket_id,
                {"category": triage["ai_category"], "priority": triage["ai_priority"],
                 "source": triage["triage_source"], "human_values_preserved": preserve_human_values},
            )
            conn.commit()
            row = conn.execute(f"SELECT {TICKET_FIELDS} FROM support_tickets WHERE ticket_id = ?", (ticket_id,)).fetchone()
            return dict(row)
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @staticmethod
    def _audit(conn, action: str, resource_id: str, details: dict) -> None:
        conn.execute(
            """INSERT INTO admin_audit_log
               (event_id, action, resource_id, details, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (
                uuid.uuid4().hex,
                action,
                resource_id,
                json.dumps(details, separators=(",", ":")),
                datetime.now().isoformat(),
            ),
        )
