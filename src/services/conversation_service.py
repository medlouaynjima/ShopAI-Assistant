"""Account-scoped persistent conversation history."""
import uuid
import json
from datetime import datetime, timedelta

from src.services.database import get_connection

MAX_HISTORY_MESSAGES = 20


class ConversationService:
    def record_agent_turn(self, customer_email: str, session_id: str, intent: str, outcome: str,
                          tool_events: list[dict], latency_ms: int) -> str:
        turn_id = uuid.uuid4().hex
        events = tool_events or []
        conn = get_connection()
        try:
            conn.execute("""INSERT INTO customer_agent_turns
                (turn_id, customer_email, session_id, intent, outcome, tool_count, tool_failures, latency_ms, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (turn_id, customer_email.strip().lower(), session_id, intent, outcome,
                 len(events), sum(not item.get("success", False) for item in events),
                 max(0, latency_ms), datetime.now().isoformat()))
            conn.commit()
            return turn_id
        finally:
            conn.close()

    def save_feedback(self, turn_id: str, customer_email: str, feedback: str) -> None:
        conn = get_connection()
        try:
            owned_turn = conn.execute(
                "SELECT 1 FROM customer_agent_turns WHERE turn_id = ? AND customer_email = ?",
                (turn_id, customer_email.strip().lower()),
            ).fetchone()
            if not owned_turn:
                raise LookupError("Agent response was not found in this account.")
            conn.execute("""INSERT INTO conversation_feedback (turn_id, customer_email, feedback, created_at)
                VALUES (?, ?, ?, ?) ON CONFLICT(turn_id, customer_email) DO UPDATE SET
                feedback=excluded.feedback, created_at=excluded.created_at""",
                (turn_id, customer_email.strip().lower(), feedback, datetime.now().isoformat()))
            conn.commit()
        finally:
            conn.close()

    def get_messages(
        self, customer_email: str, session_id: str, limit: int = MAX_HISTORY_MESSAGES
    ) -> list[dict]:
        safe_limit = max(1, min(limit, 50))
        conn = get_connection()
        try:
            rows = conn.execute(
                """SELECT role, content, created_at, turn_id FROM conversation_messages
                   WHERE customer_email = ? AND session_id = ?
                   ORDER BY created_at DESC, message_id DESC LIMIT ?""",
                (customer_email.strip().lower(), session_id, safe_limit),
            ).fetchall()
            feedback_rows = conn.execute(
                "SELECT turn_id, feedback FROM conversation_feedback WHERE customer_email = ?",
                (customer_email.strip().lower(),),
            ).fetchall()
            feedback = {row["turn_id"]: row["feedback"] for row in feedback_rows}
            return [
                {
                    "role": row["role"],
                    "content": row["content"],
                    "created_at": row["created_at"],
                    "turn_id": row["turn_id"],
                    "feedback": feedback.get(row["turn_id"], "") if row["turn_id"] else "",
                }
                for row in reversed(rows)
            ]
        finally:
            conn.close()

    def save_exchange(
        self, customer_email: str, session_id: str, user_message: str,
        assistant_message: str, turn_id: str = "",
    ) -> None:
        email = customer_email.strip().lower()
        timestamp = datetime.now()
        conn = get_connection()
        try:
            conn.execute("BEGIN IMMEDIATE")
            for position, (role, content) in enumerate((
                ("user", user_message),
                ("assistant", assistant_message),
            )):
                conn.execute(
                    """INSERT INTO conversation_messages
                       (message_id, turn_id, session_id, customer_email, role, content, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        uuid.uuid4().hex,
                        turn_id or None,
                        session_id,
                        email,
                        role,
                        content,
                        (timestamp + timedelta(microseconds=position)).isoformat(),
                    ),
                )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def clear_session(self, customer_email: str, session_id: str) -> int:
        conn = get_connection()
        try:
            conn.execute("BEGIN IMMEDIATE")
            cursor = conn.execute(
                """DELETE FROM conversation_messages
                   WHERE customer_email = ? AND session_id = ?""",
                (customer_email.strip().lower(), session_id),
            )
            deleted = cursor.rowcount
            conn.commit()
            return deleted
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
