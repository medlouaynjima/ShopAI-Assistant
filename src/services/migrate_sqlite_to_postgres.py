"""Copy the existing SQLite data to PostgreSQL without deleting either database."""
from src.config import settings
from src.services.database import (
    SCHEMA,
    _PostgresConnection,
    get_connection,
    get_sqlite_connection,
)

TABLE_KEYS = {
    "orders": "order_id",
    "shipments": "tracking_number",
    "customers": "email",
    "conversation_messages": "message_id",
    "products": "sku",
    "returns": "rma_number",
    "cancellation_requests": "cancellation_id",
    "support_tickets": "ticket_id",
    "auth_sessions": "token_hash",
    "payments": "payment_id",
    "knowledge_documents": "document_id",
    "admin_audit_log": "event_id",
}


def migrate_sqlite_to_postgres() -> dict[str, int]:
    """Create the PostgreSQL schema, copy rows, and verify exact row contents."""
    if not settings.database_url:
        raise RuntimeError("Set DATABASE_URL to the target PostgreSQL database first.")

    source = get_sqlite_connection()
    destination = None
    copied: dict[str, int] = {}
    try:
        destination = get_connection()
        if not isinstance(destination, _PostgresConnection):
            raise RuntimeError("DATABASE_URL did not create a PostgreSQL connection.")
        source.execute("BEGIN")
        destination.execute("CREATE EXTENSION IF NOT EXISTS vector")
        destination.executescript(SCHEMA)
        for table, primary_key in TABLE_KEYS.items():
            rows = source.execute(f"SELECT * FROM {table}").fetchall()
            copied[table] = len(rows)
            for row in rows:
                columns = list(row.keys())
                placeholders = ", ".join("?" for _ in columns)
                column_sql = ", ".join(columns)
                destination.execute(
                    f"INSERT INTO {table} ({column_sql}) "
                    f"VALUES ({placeholders}) ON CONFLICT DO NOTHING",
                    tuple(row[column] for column in columns),
                )

                migrated = destination.execute(
                    f"SELECT * FROM {table} WHERE {primary_key} = ?",
                    (row[primary_key],),
                ).fetchone()
                if migrated is None or any(
                    migrated[column] != row[column] for column in columns
                ):
                    raise RuntimeError(
                        f"Data verification failed for {table} "
                        f"record {row[primary_key]!r}."
                    )

        destination.commit()
        return copied
    except Exception:
        if destination is not None:
            destination.rollback()
        raise
    finally:
        source.close()
        if destination is not None:
            destination.close()


if __name__ == "__main__":
    counts = migrate_sqlite_to_postgres()
    print("SQLite data copied and verified in PostgreSQL:")
    for table, count in counts.items():
        print(f"  {table}: {count} rows")
    print("The original SQLite database was left unchanged.")
