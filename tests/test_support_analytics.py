from datetime import datetime, timedelta
import uuid

import pytest


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    from src.config import settings
    from src.services import database

    monkeypatch.setattr(settings, "database_url", "")
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "support-analytics.sqlite3")
    database.init_db()
    return database


def _customer(database, email="ops@example.test"):
    conn = database.get_connection()
    try:
        now = datetime.now().isoformat()
        conn.execute("INSERT INTO customers (email, full_name, password_hash, verified_at, created_at) VALUES (?, ?, ?, ?, ?)", (email, "Ops Test", "test-hash", now, now))
        conn.commit()
    finally:
        conn.close()


def test_turn_feedback_is_customer_scoped_and_reflected_in_analytics(isolated_db):
    from src.services.admin_service import AdminService
    from src.services.conversation_service import ConversationService

    _customer(isolated_db)
    service = ConversationService()
    turn_id = service.record_agent_turn("ops@example.test", "default", "product_search", "evidence_answered", [{"name": "search_products", "success": True}], 350)
    service.save_exchange("ops@example.test", "default", "Is it in stock?", "Yes, 7 are available.", turn_id)
    with pytest.raises(LookupError):
        service.save_feedback(turn_id, "other@example.test", "helpful")
    service.save_feedback(turn_id, "ops@example.test", "helpful")
    history = service.get_messages("ops@example.test", "default")
    assert history[-1]["turn_id"] == turn_id
    assert history[-1]["feedback"] == "helpful"
    analytics = AdminService().analytics()
    assert analytics["authenticated_agent_turns"] == 1
    assert analytics["customer_confirmed_helpful_rate"] == 1
    assert analytics["average_agent_latency_ms"] == 350


def test_quality_queue_can_be_reviewed_and_cleared(isolated_db):
    from src.services.admin_service import AdminService
    from src.services.conversation_service import ConversationService

    _customer(isolated_db)
    turn_id = ConversationService().record_agent_turn("ops@example.test", "default", "general", "unverified_answer", [], 80)
    ConversationService().save_feedback(turn_id, "ops@example.test", "unresolved")
    admin = AdminService()
    assert any(row["turn_id"] == turn_id for row in admin.quality_queue())
    admin.add_quality_review(turn_id, "admin", "incorrect_answer", "Needs a grounded answer.")
    assert all(row["turn_id"] != turn_id for row in admin.quality_queue())


def test_ticket_staff_timing_notes_assignment_and_reopen_are_measured(isolated_db):
    from src.services.admin_service import AdminService

    admin = AdminService()
    now = datetime.now()
    ticket_id = f"TKT-{uuid.uuid4().hex[:10].upper()}"
    conn = isolated_db.get_connection()
    try:
        conn.execute("""INSERT INTO support_tickets
            (ticket_id, customer_email, order_id, description, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?)""",
            (ticket_id, "ops@example.test", None, "Delivery is delayed", "open", (now - timedelta(minutes=20)).isoformat()))
        conn.commit()
    finally:
        conn.close()
    admin.assign_ticket(ticket_id, "Logistics")
    admin.add_ticket_note(ticket_id, "Carrier investigation started.")
    admin.update_ticket(ticket_id, "resolved")
    admin.update_ticket(ticket_id, "open")
    ticket = next(row for row in admin.list_tickets() if row["ticket_id"] == ticket_id)
    assert ticket["assigned_team"] == "Logistics"
    assert ticket["first_staff_activity_at"]
    assert len(ticket["notes"]) == 1
    assert ticket["reopened_count"] == 1
    metrics = admin.analytics()
    assert metrics["reopened_tickets"] == 1
    assert metrics["average_minutes_to_first_staff_activity"] is not None

