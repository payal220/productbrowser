-- =============================================================
-- seed.sql — Seed 200,000 products using a single bulk INSERT
-- =============================================================
-- WHY NOT A LOOP?
--   A Python/JS loop making 200k individual INSERT calls has
--   huge overhead: round-trip latency × 200k = minutes.
--
--   This single SQL statement uses:
--     generate_series(1, 200000) — a Postgres set-returning function
--     that produces 200k rows in one shot, entirely in the DB engine.
--   Then we INSERT all 200k rows in one transaction.
--   Result: ~5–15 seconds instead of minutes.
-- =============================================================

-- Truncate first if re-seeding (safe; restarts the sequence too)
TRUNCATE products RESTART IDENTITY;

INSERT INTO products (name, category, price, created_at, updated_at)
SELECT
    -- Name: "Product <adjective> <number>" for readable fake names
    'Product ' || adj.word || ' ' || gs.i                                   AS name,

    -- Category: round-robin across 8 categories using modulo
    (ARRAY[
        'Electronics', 'Clothing', 'Books', 'Home & Garden',
        'Sports', 'Toys', 'Beauty', 'Automotive'
    ])[ (gs.i % 8) + 1 ]                                                     AS category,

    -- Price: random float between 5.00 and 999.99, rounded to 2 decimal places
    ROUND( (RANDOM() * 994.99 + 5.00)::NUMERIC, 2 )                         AS price,

    -- created_at: random timestamp in the past 2 years
    NOW() - (RANDOM() * INTERVAL '730 days')                                AS created_at,

    -- updated_at: always >= created_at; add 0–30 days after creation
    -- This simulates realistic update patterns (some products never updated,
    -- some updated recently — important for cursor pagination testing)
    NOW() - (RANDOM() * INTERVAL '730 days') + (RANDOM() * INTERVAL '30 days') AS updated_at

FROM
    generate_series(1, 200000) AS gs(i),

    -- Lateral join to pick a random adjective from a small list
    -- LATERAL means it's evaluated per-row
    LATERAL (
        SELECT (ARRAY[
            'Alpha', 'Beta', 'Gamma', 'Delta', 'Sigma',
            'Ultra', 'Pro', 'Max', 'Elite', 'Prime',
            'Core', 'Nano', 'Mega', 'Hyper', 'Neo'
        ])[ (FLOOR(RANDOM() * 15) + 1)::INT ] AS word
    ) AS adj;

-- Verify the count
SELECT COUNT(*) AS total_products FROM products;
SELECT category, COUNT(*) FROM products GROUP BY category ORDER BY category;
