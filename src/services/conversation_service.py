"""Account-scoped persistent conversation history."""
import uuid
from datetime import datetime, timedelta

from src.services.database import get_connection

MAX_HISTORY_MESSAGES = 20


class ConversationService:
    def get_messages(
        self, customer_email: str, session_id: str, limit: int = MAX_HISTORY_MESSAGES
    ) -> list[dict]:
        safe_limit = max(1, min(limit, 50))
        conn = get_connection()
        try:
            rows = conn.execute(
                """SELECT role, content, created_at FROM conversation_messages
                   WHERE customer_email = ? AND session_id = ?
                   ORDER BY created_at DESC, message_id DESC LIMIT ?""",
                (customer_email.strip().lower(), session_id, safe_limit),
            ).fetchall()
            return [
                {
                    "role": row["role"],
                    "content": row["content"],
                    "created_at": row["created_at"],
                }
                for row in reversed(rows)
            ]
        finally:
            conn.close()

    def save_exchange(
        self, customer_email: str, session_id: str, user_message: str,
        assistant_message: str,
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
                       (message_id, session_id, customer_email, role, content, created_at)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        uuid.uuid4().hex,
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
