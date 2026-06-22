-- =============================================================
-- schema.sql — PostgreSQL schema for product browsing
-- =============================================================
-- WHY THIS SCHEMA?
--   Cursor pagination needs to uniquely order every row.
--   We sort by (updated_at DESC, id ASC) so:
--     - Newest-updated products appear first
--     - `id` breaks ties when two products share the same timestamp
-- =============================================================

CREATE TABLE IF NOT EXISTS products (
    id          BIGSERIAL PRIMARY KEY,          -- auto-incrementing integer PK; unique, never null
    name        TEXT        NOT NULL,
    category    TEXT        NOT NULL,
    price       NUMERIC(10, 2) NOT NULL,        -- 10 digits total, 2 decimal places (e.g. 99999999.99)
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ---------------------------------------------------------------
-- INDEX 1 — cursor pagination index (the critical one)
-- ---------------------------------------------------------------
-- Every paginated query uses WHERE (updated_at, id) < (cursor_ts, cursor_id)
-- ORDER BY updated_at DESC, id ASC
-- This composite index lets Postgres seek straight to the cursor position
-- instead of scanning + sorting the full 200k rows on every page.
-- Without this, each page request = full table scan = O(n) per request.
CREATE INDEX IF NOT EXISTS idx_products_updated_at_id
    ON products (updated_at DESC, id ASC);

-- ---------------------------------------------------------------
-- INDEX 2 — category filter index
-- ---------------------------------------------------------------
-- When the user filters by category, Postgres uses this index to
-- find matching rows, then the cursor index to paginate within them.
-- A single-column index is enough here; Postgres can combine indexes.
CREATE INDEX IF NOT EXISTS idx_products_category
    ON products (category);

-- ---------------------------------------------------------------
-- INDEX 3 — category + cursor (composite, for filtered pagination)
-- ---------------------------------------------------------------
-- When BOTH a category filter AND cursor pagination are applied,
-- this single index handles both predicates in one scan.
-- This is more efficient than Postgres combining two separate indexes.
CREATE INDEX IF NOT EXISTS idx_products_category_updated_id
    ON products (category, updated_at DESC, id ASC);
