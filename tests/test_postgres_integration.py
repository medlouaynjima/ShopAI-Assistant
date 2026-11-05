import os

import pytest

from src.config import settings

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="TEST_DATABASE_URL is not configured.",
)


def test_postgres_schema_adapter_and_vector_extension(monkeypatch):
    from src.services.database import _PostgresConnection, get_connection, init_db
    from src.services.product_service import ProductService

    monkeypatch.setattr(settings, "database_url", TEST_DATABASE_URL)
    init_db()

    conn = get_connection()
    try:
        assert isinstance(conn, _PostgresConnection)
        assert conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0] >= 12
        extension = conn.execute(
            "SELECT 1 FROM pg_extension WHERE extname = 'vector'"
        ).fetchone()
        assert extension
    finally:
        conn.close()

    product = ProductService().get_by_sku("SKU-201")
    assert product is not None
    assert product.name == "Mechanical Keyboard"
