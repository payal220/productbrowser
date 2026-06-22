# Product Browser — Full Stack Guide

A cursor-paginated product catalogue with 200k records, FastAPI + PostgreSQL + vanilla JS.

---

## Project Structure

```
product-browser/
├── db/
│   ├── schema.sql      # Table + indexes
│   └── seed.sql        # Bulk-insert 200k products
├── backend/
│   ├── main.py         # FastAPI app
│   └── requirements.txt
├── frontend/
│   └── index.html      # Single-file UI
├── render.yaml         # Render deployment config
└── README.md
```

---

## Why Cursor Pagination? (The Core Concept)

### The Problem with OFFSET

Imagine you're on page 5 (OFFSET 100) of a product list sorted by `updated_at DESC`.
Between your page 4 and page 5 fetch, someone updates a product that was on page 3.
That product's `updated_at` changes, it jumps to page 1, and **every product shifts down one row**.
Page 5 now contains what used to be page 5's second item through page 6's first item.
**You skipped one product entirely.**

Additionally, `LIMIT 20 OFFSET 100000` is slow — Postgres reads and discards 100,000 rows before returning 20.

### How Cursors Fix This

A cursor is a bookmark: "give me everything that comes after *this specific row* in sort order."

```
Sort order: (updated_at DESC, id ASC)

Page 1: rows 1–20, last row has cursor = encode(updated_at="2024-03-15", id=42)
Page 2: WHERE (updated_at < '2024-03-15' OR (updated_at = '2024-03-15' AND id > 42))

Now, if a product is updated and jumps to page 1, it's now BEFORE your cursor.
Your page 2 query is unaffected. No duplicates, no gaps.
```

The composite index `(updated_at DESC, id ASC)` makes the cursor seek O(log n) instead of O(n).

---

## Step 1: Set Up Neon (Free Postgres)

1. Go to [neon.tech](https://neon.tech) → Sign up free
2. Create a new project → name it `product-browser`
3. Copy the connection string: `postgresql://user:pass@ep-xxx.us-east-2.aws.neon.tech/neondb?sslmode=require`
4. Open the **SQL Editor** tab in Neon dashboard
5. Paste and run `db/schema.sql` (creates table + indexes)
6. Paste and run `db/seed.sql` (inserts 200k products — takes ~10–20 seconds)

---

## Step 2: Run Locally

```bash
cd backend
pip install -r requirements.txt

# Set your Neon connection string
export DATABASE_URL="postgresql://user:pass@ep-xxx.neon.tech/neondb?sslmode=require"

uvicorn main:app --reload --port 8000
```

Test the API:
```bash
# First page
curl "http://localhost:8000/products?limit=5"

# Next page (paste next_cursor from above)
curl "http://localhost:8000/products?limit=5&cursor=YOUR_CURSOR"

# Filtered
curl "http://localhost:8000/products?category=Electronics&limit=5"

# Categories
curl "http://localhost:8000/categories"
```

Open `frontend/index.html` directly in your browser (no build step needed).

---

## Step 3: Deploy Backend to Render

1. Push this repo to GitHub
2. Go to [render.com](https://render.com) → New → Web Service
3. Connect your GitHub repo
4. Render auto-detects `render.yaml`
5. In the service's **Environment** tab, add:
   - Key: `DATABASE_URL`
   - Value: your Neon connection string
6. Click **Deploy**

Your API will be live at: `https://product-browser-api.onrender.com`

---

## Step 4: Deploy Frontend

Update `API_BASE` in `frontend/index.html`:
```javascript
const API_BASE = "https://product-browser-api.onrender.com";
```

Then deploy `frontend/index.html` anywhere static files are served:
- **Render Static Site**: New → Static Site → point to `frontend/` folder
- **Netlify**: Drag and drop the `frontend/` folder
- **GitHub Pages**: Push to `gh-pages` branch

---

## API Reference

### `GET /products`
| Param | Type | Description |
|-------|------|-------------|
| `cursor` | string | Pagination cursor (from previous response) |
| `limit` | int (1–100) | Items per page (default 20) |
| `category` | string | Filter by category |

Response:
```json
{
  "products": [...],
  "next_cursor": "base64string or null",
  "count": 20,
  "has_more": true
}
```

### `GET /categories`
Returns all distinct category names.

### `GET /health`
Returns `{"status": "ok"}`. Used by Render for health checks.

---

## Performance Notes

| Approach | 200k rows, page 5000 |
|----------|----------------------|
| OFFSET 100000 | ~800ms (scans 100k rows) |
| Cursor (with index) | ~2ms (index seek) |

The `idx_products_category_updated_id` index covers both filtering + pagination
in a single scan — no separate sort or filter step needed.

---

## Free Tier Limits

| Service | Free Tier |
|---------|-----------|
| Neon | 0.5 GB storage, 1 project |
| Render Web Service | Spins down after 15 min inactivity, 512MB RAM |
| Render Static Site | Unlimited |

> **Note**: On Render's free tier, the first request after inactivity takes ~30s (cold start).
> Upgrade to Starter ($7/mo) to keep it always on.
