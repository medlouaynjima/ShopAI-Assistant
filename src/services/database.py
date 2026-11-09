"""
Database module — persistent storage for the e-commerce support agent.

Tables:
  - orders: customer orders with items (JSON), status, tracking
  - shipments: carrier tracking with event history (JSON)
  - returns: return requests with RMA tracking and approval state
  - cancellation_requests: customer-confirmed order cancellations
  - support_tickets: escalated customer support requests
  - customers and auth_sessions: verified customer accounts and bearer sessions
  - products: store catalog and inventory
  - payments: simulated payment status records
"""
import json
import os
import re
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from src.config import settings

DB_PATH = Path(
    os.getenv("SHOPASSIST_SQLITE_PATH")
    or Path(__file__).resolve().parent.parent / "data" / "ecommerce.db"
)


class _Record(dict):
    """Mapping row that also preserves sqlite3.Row-style numeric indexing."""

    def __init__(self, names: list[str], values: tuple):
        super().__init__(zip(names, values))
        self._values = values

    def __getitem__(self, key):
        if isinstance(key, int):
            return self._values[key]
        return super().__getitem__(key)


class _PostgresResult:
    def __init__(self, cursor):
        self._cursor = cursor

    def _record(self, row):
        if row is None:
            return None
        names = [column.name for column in self._cursor.description]
        return _Record(names, row)

    def fetchone(self):
        return self._record(self._cursor.fetchone())

    def fetchall(self):
        return [self._record(row) for row in self._cursor.fetchall()]

    @property
    def rowcount(self):
        return self._cursor.rowcount


class _PostgresConnection:
    """Adapt the small SQLite connection API used by services to psycopg."""

    def __init__(self, connection):
        self._connection = connection

    @staticmethod
    def _prepare(statement: str) -> str:
        normalized = statement.strip()
        if normalized.upper() == "BEGIN IMMEDIATE":
            # Serialize critical read-check-write sequences like SQLite does.
            return "SELECT pg_advisory_xact_lock(73119421)"
        if normalized.upper().startswith("INSERT OR IGNORE INTO "):
            normalized = re.sub(
                r"^INSERT\s+OR\s+IGNORE\s+INTO\s+",
                "INSERT INTO ",
                normalized,
                flags=re.IGNORECASE,
            )
            normalized = f"{normalized.rstrip(';')} ON CONFLICT DO NOTHING"
        return re.sub(r"\?", "%s", normalized)

    def execute(self, statement: str, parameters=()):
        prepared = self._prepare(statement)
        try:
            return _PostgresResult(self._connection.execute(prepared, parameters))
        except Exception as exc:
            try:
                import psycopg
            except ImportError:
                raise
            if isinstance(exc, psycopg.IntegrityError):
                raise sqlite3.IntegrityError(str(exc)) from exc
            raise

    def executemany(self, statement: str, parameters):
        prepared = self._prepare(statement)
        return _PostgresResult(self._connection.cursor().executemany(prepared, parameters))

    def executescript(self, script: str):
        for statement in script.split(";"):
            if statement.strip():
                self.execute(statement)

    def commit(self):
        self._connection.commit()

    def rollback(self):
        self._connection.rollback()

    def close(self):
        self._connection.close()


def get_sqlite_connection() -> sqlite3.Connection:
    """Open the existing SQLite database regardless of the configured backend."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def get_connection():
    """Connect to PostgreSQL when configured; otherwise use the existing SQLite database."""
    if not settings.database_url:
        return get_sqlite_connection()
    try:
        import psycopg
    except ImportError as exc:
        raise RuntimeError(
            "PostgreSQL is configured but psycopg is not installed. "
            "Install dependencies from requirements.txt."
        ) from exc
    try:
        connection = psycopg.connect(settings.database_url)
    except psycopg.Error:
        # psycopg error strings may echo the full connection URL, including its
        # password. Keep credentials out of API responses and test tracebacks.
        raise RuntimeError(
            "Could not connect to PostgreSQL. Check DATABASE_URL and confirm the database is running."
        ) from None
    return _PostgresConnection(connection)


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

SCHEMA = """
CREATE TABLE IF NOT EXISTS orders (
    order_id       TEXT PRIMARY KEY,
    customer_name  TEXT NOT NULL,
    email          TEXT NOT NULL,
    items          TEXT NOT NULL,         -- JSON array of {product_name, sku, quantity, price}
    status         TEXT NOT NULL DEFAULT 'confirmed',
    total          REAL NOT NULL,
    created_at     TEXT NOT NULL,
    shipping_address TEXT NOT NULL,
    tracking_number TEXT
);

CREATE TABLE IF NOT EXISTS shipments (
    tracking_number TEXT PRIMARY KEY,
    carrier         TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'label_created',
    estimated_delivery TEXT,
    events          TEXT NOT NULL DEFAULT '[]'  -- JSON array of {timestamp, location, description}
);

CREATE TABLE IF NOT EXISTS returns (
    rma_number     TEXT PRIMARY KEY,
    order_id       TEXT NOT NULL REFERENCES orders(order_id),
    reason         TEXT NOT NULL,
    status         TEXT NOT NULL DEFAULT 'pending',
    refund_amount  REAL NOT NULL,
    created_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS cancellation_requests (
    cancellation_id TEXT PRIMARY KEY,
    order_id        TEXT NOT NULL REFERENCES orders(order_id),
    status          TEXT NOT NULL DEFAULT 'pending_confirmation',
    created_at      TEXT NOT NULL,
    confirmed_at    TEXT
);

CREATE TABLE IF NOT EXISTS support_tickets (
    ticket_id       TEXT PRIMARY KEY,
    customer_email  TEXT NOT NULL,
    order_id        TEXT,
    description     TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'open',
    created_at      TEXT NOT NULL,
    category        TEXT NOT NULL DEFAULT 'other',
    priority        TEXT NOT NULL DEFAULT 'normal',
    ai_category     TEXT NOT NULL DEFAULT 'other',
    ai_priority     TEXT NOT NULL DEFAULT 'normal',
    triage_summary  TEXT NOT NULL DEFAULT '',
    suggested_team TEXT NOT NULL DEFAULT 'Customer care',
    triage_reason   TEXT NOT NULL DEFAULT 'Awaiting triage.',
    triage_confidence REAL NOT NULL DEFAULT 0,
    triage_source   TEXT NOT NULL DEFAULT 'untriaged',
    subcategory     TEXT NOT NULL DEFAULT '',
    suggested_next_action TEXT NOT NULL DEFAULT '',
    assigned_team   TEXT NOT NULL DEFAULT '',
    first_staff_activity_at TEXT,
    resolved_at     TEXT,
    reopened_count  INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS support_ticket_notes (
    note_id       TEXT PRIMARY KEY,
    ticket_id     TEXT NOT NULL REFERENCES support_tickets(ticket_id) ON DELETE CASCADE,
    author        TEXT NOT NULL,
    note          TEXT NOT NULL,
    created_at    TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_ticket_notes_created
    ON support_ticket_notes(ticket_id, created_at);

CREATE TABLE IF NOT EXISTS customers (
    email                 TEXT PRIMARY KEY,
    full_name             TEXT NOT NULL,
    password_hash         TEXT NOT NULL,
    verified_at           TEXT,
    verification_hash     TEXT,
    verification_expires  TEXT,
    verification_sent_at  TEXT,
    verification_attempts INTEGER NOT NULL DEFAULT 0,
    created_at            TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS customer_agent_turns (
    turn_id       TEXT PRIMARY KEY,
    customer_email TEXT NOT NULL REFERENCES customers(email),
    session_id    TEXT NOT NULL,
    intent        TEXT NOT NULL,
    outcome       TEXT NOT NULL,
    tool_count    INTEGER NOT NULL DEFAULT 0,
    tool_failures INTEGER NOT NULL DEFAULT 0,
    latency_ms    INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_agent_turns_customer_created
    ON customer_agent_turns(customer_email, created_at);

CREATE TABLE IF NOT EXISTS conversation_feedback (
    turn_id       TEXT NOT NULL REFERENCES customer_agent_turns(turn_id) ON DELETE CASCADE,
    customer_email TEXT NOT NULL REFERENCES customers(email),
    feedback      TEXT NOT NULL CHECK (feedback IN ('helpful', 'not_helpful', 'unresolved')),
    created_at    TEXT NOT NULL,
    PRIMARY KEY (turn_id, customer_email)
);

CREATE TABLE IF NOT EXISTS quality_reviews (
    review_id TEXT PRIMARY KEY,
    turn_id TEXT NOT NULL REFERENCES customer_agent_turns(turn_id) ON DELETE CASCADE,
    reviewer TEXT NOT NULL,
    label TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS auth_sessions (
    token_hash TEXT PRIMARY KEY,
    email      TEXT NOT NULL REFERENCES customers(email),
    expires_at TEXT NOT NULL,
    revoked_at TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS products (
    sku          TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    category     TEXT NOT NULL,
    description  TEXT NOT NULL,
    price        REAL NOT NULL,
    inventory    INTEGER NOT NULL DEFAULT 0 CHECK (inventory >= 0),
    active       INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS payments (
    payment_id   TEXT PRIMARY KEY,
    order_id     TEXT NOT NULL UNIQUE REFERENCES orders(order_id),
    status       TEXT NOT NULL,
    amount       REAL NOT NULL,
    provider     TEXT NOT NULL DEFAULT 'demo',
    updated_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS conversation_messages (
    message_id    TEXT PRIMARY KEY,
    turn_id       TEXT,
    session_id    TEXT NOT NULL,
    customer_email TEXT NOT NULL REFERENCES customers(email),
    role          TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content       TEXT NOT NULL,
    created_at    TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_conversation_owner_session
    ON conversation_messages(customer_email, session_id, created_at);

CREATE TABLE IF NOT EXISTS knowledge_documents (
    document_id TEXT PRIMARY KEY,
    source      TEXT NOT NULL,
    title       TEXT NOT NULL,
    content     TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS knowledge_chunks (
    chunk_id    TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES knowledge_documents(document_id) ON DELETE CASCADE,
    ordinal     INTEGER NOT NULL,
    content     TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    UNIQUE(document_id, ordinal)
);

CREATE TABLE IF NOT EXISTS admin_audit_log (
    event_id    TEXT PRIMARY KEY,
    action      TEXT NOT NULL,
    resource_id TEXT NOT NULL,
    details     TEXT NOT NULL,
    created_at  TEXT NOT NULL
);
"""


def init_db():
    """Create tables and seed data if empty."""
    conn = get_connection()
    try:
        if isinstance(conn, _PostgresConnection):
            conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        conn.executescript(SCHEMA)
        if isinstance(conn, _PostgresConnection):
            conn.execute(
                "ALTER TABLE knowledge_documents "
                "ADD COLUMN IF NOT EXISTS embedding vector(768)"
            )
            conn.execute(
                "ALTER TABLE knowledge_chunks "
                "ADD COLUMN IF NOT EXISTS embedding vector(768)"
            )
            conn.execute(
                """CREATE INDEX IF NOT EXISTS idx_knowledge_chunk_embedding_hnsw
                   ON knowledge_chunks USING hnsw (embedding vector_cosine_ops)"""
            )

        _ensure_ticket_triage_columns(conn)

        # Only seed if database is empty
        count = conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
        if count == 0:
            _seed_data(conn)
        _seed_products_and_payments(conn)

        conn.commit()
    finally:
        conn.close()
    from src.services.knowledge_service import sync_knowledge_base

    sync_knowledge_base()


def _ensure_ticket_triage_columns(conn) -> None:
    """Add triage fields to existing databases without replacing ticket data."""
    columns = {
        "category": "TEXT NOT NULL DEFAULT 'other'",
        "priority": "TEXT NOT NULL DEFAULT 'normal'",
        "ai_category": "TEXT NOT NULL DEFAULT 'other'",
        "ai_priority": "TEXT NOT NULL DEFAULT 'normal'",
        "triage_summary": "TEXT NOT NULL DEFAULT ''",
        "suggested_team": "TEXT NOT NULL DEFAULT 'Customer care'",
        "triage_reason": "TEXT NOT NULL DEFAULT 'Awaiting triage.'",
        "triage_confidence": "REAL NOT NULL DEFAULT 0",
        "triage_source": "TEXT NOT NULL DEFAULT 'untriaged'",
        "subcategory": "TEXT NOT NULL DEFAULT ''",
        "suggested_next_action": "TEXT NOT NULL DEFAULT ''",
        "assigned_team": "TEXT NOT NULL DEFAULT ''",
        "first_staff_activity_at": "TEXT",
        "resolved_at": "TEXT",
        "reopened_count": "INTEGER NOT NULL DEFAULT 0",
    }
    if isinstance(conn, _PostgresConnection):
        for name, declaration in columns.items():
            conn.execute(
                f"ALTER TABLE support_tickets ADD COLUMN IF NOT EXISTS {name} {declaration}"
            )
        conn.execute(
            "ALTER TABLE conversation_messages ADD COLUMN IF NOT EXISTS turn_id TEXT"
        )
        return

    existing = {row["name"] for row in conn.execute("PRAGMA table_info(support_tickets)").fetchall()}
    for name, declaration in columns.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE support_tickets ADD COLUMN {name} {declaration}")
    message_columns = {
        row["name"] for row in conn.execute("PRAGMA table_info(conversation_messages)").fetchall()
    }
    if "turn_id" not in message_columns:
        conn.execute("ALTER TABLE conversation_messages ADD COLUMN turn_id TEXT")


# ---------------------------------------------------------------------------
# Seed Data — 12 orders, diverse scenarios
# ---------------------------------------------------------------------------

def _seed_products_and_payments(conn):
    products = [
        ("SKU-501", "Wireless Headphones", "Audio", "Over-ear wireless headphones with noise isolation.", 79.99, 18),
        ("SKU-102", "USB-C Cable", "Accessories", "Durable 1m USB-C charging and data cable.", 12.99, 120),
        ("SKU-201", "Mechanical Keyboard", "Computers", "Tenkeyless mechanical keyboard with tactile switches.", 149.99, 7),
        ("SKU-305", "27-inch 4K Monitor", "Computers", "27-inch 4K UHD monitor with adjustable stand.", 499.99, 3),
        ("SKU-410", "Wireless Mouse", "Accessories", "Ergonomic wireless mouse with adjustable DPI.", 49.99, 32),
        ("SKU-411", "XL Mousepad", "Accessories", "Extended desk mousepad with non-slip base.", 19.99, 45),
        ("SKU-601", "Wireless Charger", "Mobile", "Qi-compatible wireless charging pad.", 39.99, 21),
        ("SKU-701", "Tablet Stand", "Mobile", "Adjustable aluminum tablet stand.", 29.99, 14),
        ("SKU-702", "Screen Protector", "Mobile", "Tempered-glass tablet screen protector.", 9.99, 66),
        ("SKU-801", "1TB Portable SSD", "Storage", "Portable USB-C solid-state drive, 1TB.", 129.99, 9),
        ("SKU-901", "Smartwatch Pro", "Wearables", "Smartwatch with activity tracking and notifications.", 299.99, 5),
        ("SKU-1001", "Bluetooth Speaker", "Audio", "Portable Bluetooth speaker with stereo sound.", 89.99, 26),
        ("SKU-1101", "Laptop Sleeve", "Accessories", "Padded 14-inch laptop sleeve.", 34.99, 0),
        ("SKU-1201", "HD Webcam", "Computers", "1080p USB webcam with privacy cover.", 89.99, 11),
        ("SKU-1301", "Phone Case", "Mobile", "Protective slim-fit phone case.", 24.99, 58),
        ("SKU-1302", "Car Charger", "Mobile", "Dual-port fast USB car charger.", 19.99, 37),
    ]
    conn.executemany(
        """INSERT OR IGNORE INTO products
           (sku, name, category, description, price, inventory)
           VALUES (?, ?, ?, ?, ?, ?)""",
        products,
    )

    now = datetime.now().isoformat()
    conn.execute(
        """INSERT OR IGNORE INTO payments
           (payment_id, order_id, status, amount, provider, updated_at)
           SELECT 'PAY-' || order_id, order_id,
                  CASE WHEN status = 'cancelled' THEN 'failed'
                       WHEN status = 'confirmed' THEN 'pending'
                       ELSE 'paid' END,
                  total, 'demo', ?
           FROM orders""",
        (now,),
    )


def _seed_data(conn):
    now = datetime.now()

    # --- Orders (12 orders, diverse scenarios) ---
    orders = [
        ("ORD-1001", "James Wilson", "james@example.com",
         [{"product_name": "Wireless Headphones", "sku": "SKU-501", "quantity": 1, "price": 79.99},
          {"product_name": "USB-C Cable", "sku": "SKU-102", "quantity": 2, "price": 12.99}],
         "delivered", 105.97, (now - timedelta(days=12)).isoformat(),
         "742 Evergreen Terrace, Springfield, IL 62701", "FDX-78901234"),

        ("ORD-1002", "Sarah Chen", "sarah@example.com",
         [{"product_name": "Mechanical Keyboard", "sku": "SKU-201", "quantity": 1, "price": 149.99}],
         "shipped", 149.99, (now - timedelta(days=4)).isoformat(),
         "221B Baker Street, London, NW1 6XE", "UPS-45678901"),

        ("ORD-1003", "Marcus Rivera", "marcus@example.com",
         [{"product_name": "27\" 4K Monitor", "sku": "SKU-305", "quantity": 1, "price": 499.99}],
         "confirmed", 499.99, (now - timedelta(hours=6)).isoformat(),
         "350 Fifth Avenue, New York, NY 10118", None),

        ("ORD-1004", "Emily Foster", "emily@example.com",
         [{"product_name": "Wireless Mouse", "sku": "SKU-410", "quantity": 1, "price": 49.99},
          {"product_name": "XL Mousepad", "sku": "SKU-411", "quantity": 1, "price": 19.99}],
         "cancelled", 69.98, (now - timedelta(days=3)).isoformat(),
         "1 Infinite Loop, Cupertino, CA 95014", None),

        ("ORD-1005", "David Kim", "david@example.com",
         [{"product_name": "Wireless Charger", "sku": "SKU-601", "quantity": 1, "price": 39.99}],
         "delivered", 39.99, (now - timedelta(days=5)).isoformat(),
         "1600 Amphitheatre Pkwy, Mountain View, CA 94043", "DHL-11223344"),

        ("ORD-1006", "Olivia Brown", "olivia@example.com",
         [{"product_name": "Tablet Stand", "sku": "SKU-701", "quantity": 1, "price": 29.99},
          {"product_name": "Screen Protector", "sku": "SKU-702", "quantity": 2, "price": 9.99}],
         "shipped", 49.97, (now - timedelta(days=2)).isoformat(),
         "4059 Mt Lee Dr, Hollywood, CA 90068", "UPS-99887766"),

        ("ORD-1007", "Alex Turner", "alex@example.com",
         [{"product_name": "1TB Portable SSD", "sku": "SKU-801", "quantity": 1, "price": 129.99}],
         "confirmed", 129.99, (now - timedelta(hours=2)).isoformat(),
         "10 Downing Street, London, SW1A 2AA", None),

        ("ORD-1008", "Sophia Martinez", "sophia@example.com",
         [{"product_name": "Smartwatch Pro", "sku": "SKU-901", "quantity": 1, "price": 299.99}],
         "delivered", 299.99, (now - timedelta(days=16)).isoformat(),
         "5th Ave & 59th St, New York, NY 10022", "FDX-55667788"),

        ("ORD-1009", "Daniel Park", "daniel@example.com",
         [{"product_name": "Bluetooth Speaker", "sku": "SKU-1001", "quantity": 1, "price": 89.99}],
         "delivered", 89.99, (now - timedelta(days=1)).isoformat(),
         "100 Broadway, New York, NY 10005", "DHL-99001122"),

        ("ORD-1010", "Rachel Green", "rachel@example.com",
         [{"product_name": "Laptop Sleeve", "sku": "SKU-1101", "quantity": 1, "price": 34.99}],
         "shipped", 34.99, (now - timedelta(days=6)).isoformat(),
         "90 Bedford St, New York, NY 10014", "FDX-33445566"),

        ("ORD-1011", "James Wilson", "james@example.com",
         [{"product_name": "HD Webcam", "sku": "SKU-1201", "quantity": 1, "price": 89.99}],
         "shipped", 89.99, (now - timedelta(days=1)).isoformat(),
         "742 Evergreen Terrace, Springfield, IL 62701", "UPS-11223344"),

        ("ORD-1012", "Grace Patel", "grace@example.com",
         [{"product_name": "Wireless Earbuds", "sku": "SKU-501", "quantity": 2, "price": 79.99},
          {"product_name": "Phone Case", "sku": "SKU-1301", "quantity": 1, "price": 24.99},
          {"product_name": "Car Charger", "sku": "SKU-1302", "quantity": 1, "price": 19.99}],
         "delivered", 204.96, (now - timedelta(days=7)).isoformat(),
         "555 Market St, San Francisco, CA 94105", "DHL-77889900"),
    ]

    for o in orders:
        conn.execute(
            "INSERT INTO orders VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (o[0], o[1], o[2], json.dumps(o[3], ensure_ascii=False),
             o[4], o[5], o[6], o[7], o[8]),
        )

    # --- Shipments (9 tracking records) ---
    shipments = [
        ("FDX-78901234", "FedEx", "delivered",
         (now - timedelta(days=2)).strftime("%Y-%m-%d"),
         [
             {"timestamp": (now - timedelta(days=12)).isoformat(), "location": "Chicago, IL", "description": "Package picked up"},
             {"timestamp": (now - timedelta(days=10)).isoformat(), "location": "Memphis, TN", "description": "Arrived at FedEx hub"},
             {"timestamp": (now - timedelta(days=4)).isoformat(), "location": "Springfield, IL", "description": "Out for delivery"},
             {"timestamp": (now - timedelta(days=2)).isoformat(), "location": "Springfield, IL", "description": "Delivered"},
         ]),

        ("UPS-45678901", "UPS", "in_transit",
         (now + timedelta(days=2)).strftime("%Y-%m-%d"),
         [
             {"timestamp": (now - timedelta(days=4)).isoformat(), "location": "London, UK", "description": "Package picked up"},
             {"timestamp": (now - timedelta(days=1)).isoformat(), "location": "Stansted, UK", "description": "Processing at UPS facility"},
         ]),

        ("DHL-11223344", "DHL", "delivered",
         (now - timedelta(days=3)).strftime("%Y-%m-%d"),
         [
             {"timestamp": (now - timedelta(days=5)).isoformat(), "location": "San Jose, CA", "description": "Package picked up"},
             {"timestamp": (now - timedelta(days=3)).isoformat(), "location": "Mountain View, CA", "description": "Delivered"},
         ]),

        ("UPS-99887766", "UPS", "out_for_delivery",
         now.strftime("%Y-%m-%d"),
         [
             {"timestamp": (now - timedelta(days=2)).isoformat(), "location": "Burbank, CA", "description": "Package picked up"},
             {"timestamp": (now - timedelta(hours=6)).isoformat(), "location": "Hollywood, CA", "description": "Out for delivery"},
         ]),

        ("FDX-55667788", "FedEx", "delivered",
         (now - timedelta(days=16)).strftime("%Y-%m-%d"),
         [
             {"timestamp": (now - timedelta(days=16)).isoformat(), "location": "Newark, NJ", "description": "Package picked up"},
             {"timestamp": (now - timedelta(days=16)).isoformat(), "location": "New York, NY", "description": "Delivered"},
         ]),

        ("DHL-99001122", "DHL", "delivered",
         (now - timedelta(days=1)).strftime("%Y-%m-%d"),
         [
             {"timestamp": (now - timedelta(days=3)).isoformat(), "location": "Jersey City, NJ", "description": "Package picked up"},
             {"timestamp": (now - timedelta(days=1)).isoformat(), "location": "New York, NY", "description": "Delivered"},
         ]),

        ("FDX-33445566", "FedEx", "in_transit",
         (now + timedelta(days=4)).strftime("%Y-%m-%d"),
         [
             {"timestamp": (now - timedelta(days=6)).isoformat(), "location": "New York, NY", "description": "Package picked up"},
             {"timestamp": (now - timedelta(days=3)).isoformat(), "location": "Paris, FR", "description": "International transit hub"},
         ]),

        ("UPS-11223344", "UPS", "in_transit",
         (now + timedelta(days=1)).strftime("%Y-%m-%d"),
         [
             {"timestamp": (now - timedelta(days=1)).isoformat(), "location": "Springfield, IL", "description": "Package picked up"},
             {"timestamp": (now - timedelta(hours=3)).isoformat(), "location": "Chicago, IL", "description": "Arrived at local facility"},
         ]),

        ("DHL-77889900", "DHL", "delivered",
         (now - timedelta(days=5)).strftime("%Y-%m-%d"),
         [
             {"timestamp": (now - timedelta(days=7)).isoformat(), "location": "Oakland, CA", "description": "Package picked up"},
             {"timestamp": (now - timedelta(days=5)).isoformat(), "location": "San Francisco, CA", "description": "Delivered"},
         ]),
    ]

    for s in shipments:
        conn.execute(
            "INSERT INTO shipments VALUES (?, ?, ?, ?, ?)",
            (s[0], s[1], s[2], s[3], json.dumps(s[4], ensure_ascii=False)),
        )

    conn.commit()
    print(f"✅ Database seeded: {len(orders)} orders, {len(shipments)} shipments")
