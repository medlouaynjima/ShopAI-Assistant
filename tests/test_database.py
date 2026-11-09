from src.services.database import _PostgresConnection, _Record
import tempfile
from pathlib import Path
import pytest


@pytest.fixture(scope="module", autouse=True)
def _setup_database():
    """Database service tests always use a disposable seeded SQLite database."""
    from src.config import settings
    import src.services.database as database

    previous_url, previous_redis, previous_path = settings.database_url, settings.redis_url, database.DB_PATH
    with tempfile.TemporaryDirectory(prefix="shopassist-database-tests-") as temp_dir:
        settings.database_url = ""
        settings.redis_url = ""
        database.DB_PATH = Path(temp_dir) / "database-tests.sqlite3"
        database.init_db()
        yield
    settings.database_url, settings.redis_url, database.DB_PATH = previous_url, previous_redis, previous_path


def test_postgres_query_placeholder_conversion():
    assert _PostgresConnection._prepare(
        "SELECT * FROM orders WHERE order_id = ?"
    ) == "SELECT * FROM orders WHERE order_id = %s"


def test_postgres_ignore_insert_conversion():
    assert _PostgresConnection._prepare(
        "INSERT OR IGNORE INTO products (sku, name) VALUES (?, ?)"
    ) == (
        "INSERT INTO products (sku, name) VALUES (%s, %s) "
        "ON CONFLICT DO NOTHING"
    )


def test_postgres_begin_immediate_uses_driver_managed_transaction():
    assert _PostgresConnection._prepare("BEGIN IMMEDIATE") == (
        "SELECT pg_advisory_xact_lock(73119421)"
    )


def test_postgres_record_supports_named_and_numeric_access():
    row = _Record(["sku", "name"], ("SKU-1", "Keyboard"))

    assert row["sku"] == row[0] == "SKU-1"
    assert row["name"] == row[1] == "Keyboard"


def test_postgres_connection_errors_do_not_expose_connection_credentials(monkeypatch):
    import psycopg
    import pytest

    from src.config import settings
    from src.services import database

    secret = "do-not-print-this-password"
    monkeypatch.setattr(settings, "database_url", f"postgresql://user:{secret}@localhost/db")

    def fail_connect(_connection_url):
        raise psycopg.OperationalError(f"connection failed for password={secret}")

    monkeypatch.setattr(psycopg, "connect", fail_connect)
    with pytest.raises(RuntimeError, match="Could not connect to PostgreSQL") as error:
        database.get_connection()

    assert secret not in str(error.value)
    assert error.value.__suppress_context__


def test_return_window_uses_delivery_time_not_order_creation_time(monkeypatch):
    from datetime import datetime, timedelta

    from src.services import order_service
    from src.services.order_service import Order
    from src.services.shipping_service import Shipment, TrackingEvent

    order = Order(
        order_id="ORD-OLD-RECENTLY-DELIVERED",
        customer_name="Demo Customer",
        email="demo@example.com",
        items=[],
        status="delivered",
        total=10,
        created_at=(datetime.now() - timedelta(days=30)).isoformat(),
        shipping_address="",
        tracking_number="FDX-TEST",
    )
    shipment = Shipment(
        tracking_number="FDX-TEST",
        carrier="FedEx",
        status="delivered",
        estimated_delivery="",
        events=[TrackingEvent(
            timestamp=(datetime.now() - timedelta(days=2)).isoformat(),
            location="Demo",
            description="Delivered",
        )],
    )
    monkeypatch.setattr(order_service.OrderService, "get_order", lambda _self, _order_id: order)
    monkeypatch.setattr(order_service.ShippingService, "track", lambda _self, _tracking_number: shipment)

    eligible, message = order_service.OrderService().can_return(order.order_id)

    assert eligible
    assert "eligible" in message.lower()


def test_return_window_rejects_delivery_older_than_fourteen_days(monkeypatch):
    from datetime import datetime, timedelta

    from src.services import order_service
    from src.services.order_service import Order
    from src.services.shipping_service import Shipment, TrackingEvent

    order = Order(
        order_id="ORD-RECENT-OLD-DELIVERY",
        customer_name="Demo Customer",
        email="demo@example.com",
        items=[],
        status="delivered",
        total=10,
        created_at=(datetime.now() - timedelta(days=2)).isoformat(),
        shipping_address="",
        tracking_number="UPS-TEST",
    )
    shipment = Shipment(
        tracking_number="UPS-TEST",
        carrier="UPS",
        status="delivered",
        estimated_delivery="",
        events=[TrackingEvent(
            timestamp=(datetime.now() - timedelta(days=16)).isoformat(),
            location="Demo",
            description="Package delivered",
        )],
    )
    monkeypatch.setattr(order_service.OrderService, "get_order", lambda _self, _order_id: order)
    monkeypatch.setattr(order_service.ShippingService, "track", lambda _self, _tracking_number: shipment)

    eligible, message = order_service.OrderService().can_return(order.order_id)

    assert not eligible
    assert "14-day" in message


def test_knowledge_search_returns_citations_for_policy():
    from src.services.knowledge_service import search_knowledge

    results = search_knowledge("return policy refund shipping 14 days")

    assert results
    assert any("returns" in result["source"] for result in results)
    assert all(result["content"] and result["score"] > 0 for result in results)


def test_knowledge_search_does_not_invent_sources_for_unmatched_query():
    from src.services.knowledge_service import format_evidence, search_knowledge

    assert search_knowledge("quantum bicycle purple comet") == []
    assert "couldn't find a matching answer" in format_evidence(
        "quantum bicycle purple comet"
    )


def test_return_window_answer_is_concise_and_uses_the_return_policy_only():
    from src.services.knowledge_service import format_evidence

    answer = format_evidence("What is your return window?")

    assert "14 days" in answer
    assert "knowledge/returns_policy.md" in answer
    assert "Use only the following" not in answer
    assert "Payments and refunds" not in answer


def test_product_catalog_is_indexed_for_grounded_search():
    from src.services.knowledge_service import search_knowledge

    results = search_knowledge("mechanical keyboard in stock")

    assert any(result["source"] == "products/SKU-201" for result in results)


def test_conversation_history_is_scoped_to_customer_and_can_be_cleared():
    import uuid
    from datetime import datetime

    from src.services.conversation_service import ConversationService
    from src.services.database import get_connection

    email = f"history-{uuid.uuid4().hex}@example.com"
    session_id = uuid.uuid4().hex
    conn = get_connection()
    try:
        conn.execute(
            """INSERT INTO customers
               (email, full_name, password_hash, created_at)
               VALUES (?, ?, ?, ?)""",
            (email, "History Test", "test-hash", datetime.now().isoformat()),
        )
        conn.commit()
    finally:
        conn.close()

    service = ConversationService()
    try:
        service.save_exchange(email, session_id, "user question", "assistant answer")
        messages = service.get_messages(email, session_id)

        assert [message["role"] for message in messages] == ["user", "assistant"]
        assert service.get_messages("other@example.com", session_id) == []
        assert service.clear_session(email, session_id) == 2
        assert service.get_messages(email, session_id) == []
    finally:
        conn = get_connection()
        try:
            conn.execute("DELETE FROM conversation_messages WHERE customer_email = ?", (email,))
            conn.execute("DELETE FROM customers WHERE email = ?", (email,))
            conn.commit()
        finally:
            conn.close()


def test_admin_ticket_status_change_is_audited():
    import uuid
    from datetime import datetime

    from src.services.admin_service import AdminService
    from src.services.database import get_connection

    ticket_id = f"TKT-{uuid.uuid4().hex[:12].upper()}"
    conn = get_connection()
    try:
        conn.execute(
            """INSERT INTO support_tickets
               (ticket_id, customer_email, order_id, description, status, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                ticket_id,
                "admin-test@example.com",
                None,
                "Admin dashboard test",
                "open",
                datetime.now().isoformat(),
            ),
        )
        conn.commit()
    finally:
        conn.close()

    service = AdminService()
    try:
        result = service.update_ticket(ticket_id, "in_progress")
        assert result["status"] == "in_progress"
        assert any(ticket["ticket_id"] == ticket_id for ticket in service.list_tickets())

        conn = get_connection()
        try:
            audit = conn.execute(
                """SELECT action, resource_id FROM admin_audit_log
                   WHERE resource_id = ?""",
                (ticket_id,),
            ).fetchone()
            assert audit["action"] == "ticket_status_updated"
        finally:
            conn.close()
    finally:
        conn = get_connection()
        try:
            conn.execute("DELETE FROM admin_audit_log WHERE resource_id = ?", (ticket_id,))
            conn.execute("DELETE FROM support_tickets WHERE ticket_id = ?", (ticket_id,))
            conn.commit()
        finally:
            conn.close()
