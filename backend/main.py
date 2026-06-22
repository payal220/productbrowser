"""
main.py — FastAPI backend for cursor-paginated product browsing
===============================================================

WHY CURSOR PAGINATION INSTEAD OF OFFSET?
-----------------------------------------
OFFSET pagination: SELECT ... LIMIT 20 OFFSET 1000
  Problem 1 — INCONSISTENCY: If a product is updated (changing its updated_at)
    between page 1 and page 2, it moves position. With offset, you'd either
    SEE IT TWICE (if it moved earlier) or SKIP IT (if it moved later).
  Problem 2 — PERFORMANCE: OFFSET 100000 means Postgres scans and discards
    100,000 rows before returning 20. Slow, wasteful, O(n) per page.

CURSOR pagination: WHERE (updated_at, id) < (cursor_ts, cursor_id) ORDER BY updated_at DESC, id ASC LIMIT 20
  Solution 1 — CONSISTENCY: The cursor is an absolute position in the sort order.
    Items you've already seen stay behind the cursor. New/updated items that land
    *after* your cursor position don't affect pages you haven't fetched yet.
  Solution 2 — PERFORMANCE: With the composite index on (updated_at DESC, id ASC),
    Postgres seeks directly to the cursor row — O(log n), not O(n).

THE CURSOR FORMAT
-----------------
We encode the cursor as base64(updated_at_iso + "," + id).
  - Base64 keeps the cursor opaque (clients can't/shouldn't parse it)
  - The comma-separated pair encodes both sort dimensions

SORT ORDER: (updated_at DESC, id ASC)
  - Descending on updated_at → most recently updated products come first
    (a reasonable default for a product catalogue)
  - Ascending on id → stable tiebreaker when two products share the same timestamp
    (timestamps have microsecond precision but concurrent writes can collide)
"""

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
import asyncpg
import os
import base64
from datetime import datetime
from typing import Optional

app = FastAPI(title="Product Browser API", version="1.0.0")

# ---------------------------------------------------------------
# CORS — allow the frontend (any origin in dev, restrict in prod)
# ---------------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],       # Replace with your frontend URL in production
    allow_methods=["GET"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------
# DATABASE CONNECTION POOL
# ---------------------------------------------------------------
# We use a connection pool (min 5, max 20 connections).
# asyncpg is the fastest async Postgres driver for Python.
# A pool reuses connections instead of opening a new TCP connection
# per request (which would add ~10–50ms per request).
DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://user:pass@localhost:5432/products")

@app.on_event("startup")
async def startup():
    app.state.pool = await asyncpg.create_pool(
        DATABASE_URL,
        min_size=5,
        max_size=20,
        # Neon (serverless Postgres) needs SSL
        ssl="require" if "neon.tech" in DATABASE_URL else None,
    )

@app.on_event("shutdown")
async def shutdown():
    await app.state.pool.close()

# ---------------------------------------------------------------
# CURSOR ENCODE / DECODE
# ---------------------------------------------------------------

def encode_cursor(updated_at: datetime, id: int) -> str:
    """
    Pack (updated_at, id) into a base64 string.
    Example: "2024-03-15T10:30:00.123456+00:00,42" → "MjAyNC0wMy..."
    """
    raw = f"{updated_at.isoformat()},{id}"
    return base64.urlsafe_b64encode(raw.encode()).decode()

def decode_cursor(cursor: str) -> tuple[datetime, int]:
    """
    Unpack base64 cursor back to (updated_at, id).
    Raises ValueError if cursor is malformed — handled by the endpoint.
    """
    raw = base64.urlsafe_b64decode(cursor.encode()).decode()
    ts_str, id_str = raw.rsplit(",", 1)       # rsplit so ISO timestamps (which contain colons) aren't split
    return datetime.fromisoformat(ts_str), int(id_str)

# ---------------------------------------------------------------
# GET /products — paginated product list
# ---------------------------------------------------------------

@app.get("/products")
async def get_products(
    cursor: Optional[str] = Query(None, description="Pagination cursor from previous response"),
    limit: int = Query(20, ge=1, le=100, description="Items per page (1–100)"),
    category: Optional[str] = Query(None, description="Filter by category name"),
):
    """
    Returns a page of products with cursor-based pagination.

    FIRST PAGE: GET /products?limit=20
    NEXT PAGE:  GET /products?limit=20&cursor=<next_cursor from response>
    FILTERED:   GET /products?category=Electronics&limit=20
    """

    # --- Build the WHERE clause dynamically ---
    # We use parameterised queries ($1, $2, ...) to prevent SQL injection.
    # Parameters are collected in order and passed to asyncpg.

    conditions = []
    params = []
    param_idx = 1  # asyncpg uses $1, $2, ... (1-indexed)

    # --- Cursor condition ---
    # "Give me rows that come AFTER the cursor in our sort order"
    # Sort order: updated_at DESC, id ASC
    # "After" in this order means:
    #   - updated_at is older (smaller timestamp), OR
    #   - updated_at is equal AND id is larger
    # SQL: (updated_at, id) < (cursor_ts, cursor_id) doesn't work for mixed ASC/DESC.
    # We must expand it manually:
    #   (updated_at < cursor_ts) OR (updated_at = cursor_ts AND id > cursor_id)
    if cursor:
        try:
            cursor_ts, cursor_id = decode_cursor(cursor)
        except Exception:
            return {"error": "Invalid cursor", "products": [], "next_cursor": None}

        # This is the key cursor predicate — it's an O(log n) index seek
        conditions.append(
            f"(updated_at < ${param_idx} OR (updated_at = ${param_idx} AND id > ${param_idx + 1}))"
        )
        params.extend([cursor_ts, cursor_id])
        param_idx += 2

    # --- Category filter ---
    if category:
        conditions.append(f"category = ${param_idx}")
        params.append(category)
        param_idx += 1

    # --- Assemble SQL ---
    where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""

    sql = f"""
        SELECT id, name, category, price, created_at, updated_at
        FROM products
        {where_clause}
        ORDER BY updated_at DESC, id ASC
        LIMIT ${param_idx}
    """
    params.append(limit)

    # --- Execute ---
    async with app.state.pool.acquire() as conn:
        rows = await conn.fetch(sql, *params)

    # --- Build response ---
    products = [
        {
            "id": row["id"],
            "name": row["name"],
            "category": row["category"],
            "price": float(row["price"]),    # Decimal → float for JSON
            "created_at": row["created_at"].isoformat(),
            "updated_at": row["updated_at"].isoformat(),
        }
        for row in rows
    ]

    # --- Next cursor ---
    # If we got a full page, there are probably more results.
    # The next cursor points to the LAST item we returned.
    # Next call will continue from just after that item.
    next_cursor = None
    if len(products) == limit:
        last = rows[-1]
        next_cursor = encode_cursor(last["updated_at"], last["id"])

    return {
        "products": products,
        "next_cursor": next_cursor,        # null means "you've reached the end"
        "count": len(products),
        "has_more": next_cursor is not None,
    }

# ---------------------------------------------------------------
# GET /categories — list all distinct categories for the filter UI
# ---------------------------------------------------------------

@app.get("/categories")
async def get_categories():
    async with app.state.pool.acquire() as conn:
        rows = await conn.fetch("SELECT DISTINCT category FROM products ORDER BY category")
    return {"categories": [row["category"] for row in rows]}

# ---------------------------------------------------------------
# GET /health — Render uses this for health checks
# ---------------------------------------------------------------

@app.get("/health")
async def health():
    return {"status": "ok"}
