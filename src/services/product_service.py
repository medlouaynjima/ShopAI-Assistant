"""Catalog and inventory queries."""
import hashlib
import json
import logging
import sqlite3
from dataclasses import dataclass
from functools import lru_cache

from redis import Redis
from redis.exceptions import RedisError

from src.config import settings
from src.services.database import get_connection

logger = logging.getLogger(__name__)
CACHE_TTL_SECONDS = 60


@dataclass
class Product:
    sku: str
    name: str
    category: str
    description: str
    price: float
    inventory: int


def _row_to_product(row: sqlite3.Row) -> Product:
    return Product(
        sku=row["sku"],
        name=row["name"],
        category=row["category"],
        description=row["description"],
        price=row["price"],
        inventory=row["inventory"],
    )


@lru_cache(maxsize=4)
def _redis_client(redis_url: str) -> Redis:
    return Redis.from_url(
        redis_url,
        decode_responses=True,
        socket_connect_timeout=0.25,
        socket_timeout=0.25,
    )


def _cache_key(namespace: str, values: dict) -> str:
    payload = json.dumps(values, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return f"shopassist:{namespace}:{digest}"


def _cache_get(key: str):
    if not settings.redis_url:
        return None
    try:
        value = _redis_client(settings.redis_url).get(key)
        return json.loads(value) if value else None
    except (RedisError, json.JSONDecodeError):
        logger.warning("Redis cache read failed; continuing with the database.")
        return None


def _cache_set(key: str, value) -> None:
    if not settings.redis_url:
        return
    try:
        _redis_client(settings.redis_url).setex(
            key,
            CACHE_TTL_SECONDS,
            json.dumps(value, separators=(",", ":")),
        )
    except RedisError:
        logger.warning("Redis cache write failed; continuing without cached data.")


class ProductService:
    """SQLite-backed product search and availability."""

    def search(
        self,
        query: str = "",
        category: str = "",
        in_stock: bool = False,
    ) -> list[Product]:
        cache_key = _cache_key(
            "products",
            {
                "query": query.strip().lower(),
                "category": category.strip().lower(),
                "in_stock": in_stock,
            },
        )
        cached = _cache_get(cache_key)
        if cached is not None:
            return [Product(**product) for product in cached]

        terms = []
        params: list[str] = []
        if query.strip():
            like = f"%{query.strip()}%"
            terms.append("(name LIKE ? OR description LIKE ? OR sku LIKE ?)")
            params.extend((like, like, like))
        if category.strip():
            terms.append("category LIKE ?")
            params.append(f"%{category.strip()}%")
        if in_stock:
            terms.append("inventory > 0")
        where = f"WHERE active = 1 AND {' AND '.join(terms)}" if terms else "WHERE active = 1"
        conn = get_connection()
        try:
            rows = conn.execute(
                f"SELECT * FROM products {where} ORDER BY name LIMIT 100",
                params,
            ).fetchall()
            products = [_row_to_product(row) for row in rows]
            _cache_set(cache_key, [product.__dict__ for product in products])
            return products
        finally:
            conn.close()

    def get_categories(self) -> list[str]:
        cache_key = _cache_key("categories", {})
        cached = _cache_get(cache_key)
        if cached is not None:
            return cached
        conn = get_connection()
        try:
            rows = conn.execute(
                """SELECT DISTINCT category FROM products
                   WHERE active = 1 ORDER BY category"""
            ).fetchall()
            categories = [row["category"] for row in rows]
            _cache_set(cache_key, categories)
            return categories
        finally:
            conn.close()

    def get_by_sku(self, sku: str) -> Product | None:
        normalized_sku = sku.strip().upper()
        cache_key = _cache_key("product", {"sku": normalized_sku})
        cached = _cache_get(cache_key)
        if cached is not None:
            return Product(**cached) if cached else None
        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT * FROM products WHERE sku = ? AND active = 1",
                (normalized_sku,),
            ).fetchone()
            product = _row_to_product(row) if row else None
            _cache_set(cache_key, product.__dict__ if product else {})
            return product
        finally:
            conn.close()
