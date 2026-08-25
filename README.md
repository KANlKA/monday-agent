# Skylark Drones — Monday.com BI Agent

Conversational agent that answers founder-level questions by querying two live
Monday.com boards (Deals and Work Orders), cleaning the messy data on the fly,
and using Claude to reason over computed results.

## Architecture

```
User <-> frontend/index.html <-> FastAPI (main.py) <-> agent.py (Claude tool-use loop)
                                                              |
                                                    monday_client.py (GraphQL)
                                                              |
                                                       Monday.com boards
```

- **monday_client.py** — thin GraphQL wrapper (read boards live; also used once by
  `seed_monday.py` to create boards/columns/items).
- **data_tools.py** — cleans raw Monday.com text into typed pandas DataFrames
  (numbers, dates, normalized categories) and drops stray header rows.
- **agent.py** — Claude tool-use loop. Claude decides which tool(s) to call
  (`query_deals`, `query_work_orders`, `cross_reference_deal`,
  `data_quality_report`, `generate_leadership_update`); Python does all the
  actual aggregation over pandas so numbers are never hallucinated.
- **main.py** — FastAPI, exposes `POST /chat` and `POST /leadership-summary`.
- **frontend/index.html** — placeholder chat UI, intentionally minimal for now.

Data is **never hardcoded**: every `/chat` request (per session) triggers a
live pull from Monday.com the first time, then caches in memory until
`refresh_data` is called.

## Setup

### 1. Monday.com

1. Create a free Monday.com account.
2. Get a personal API token: your avatar → **Administration → API**, or on an
   individual account, **Profile → Developers → My Access Tokens**.
3. `cd backend && cp .env.example .env` and fill in `MONDAY_API_TOKEN`.
4. Put `Deal_funnel_Data.xlsx` and `Work_Order_Tracker_Data.xlsx` in `backend/`.
5. Install deps and seed the boards:
   ```bash
   pip install -r requirements.txt
   python seed_monday.py
   ```
   This creates two boards ("Deals - Sales Pipeline", "Work Orders - Execution")
   with typed columns (date, numbers, status, text) and imports every row.
   It prints two board IDs at the end — copy them into `.env`:
   ```
   MONDAY_DEALS_BOARD_ID=...
   MONDAY_WORKORDERS_BOARD_ID=...
   ```

### 2. Anthropic API

Get a key from console.anthropic.com and add it to `.env` as `ANTHROPIC_API_KEY`.

### 3. Run the backend

```bash
cd backend
python main.py
# serves on http://localhost:8000
```

### 4. Try it

```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "How is our pipeline looking for the mining sector?"}'
```

Or open `frontend/index.html` in a browser (edit `API_BASE` if deploying).

## Deploying (hosted prototype)

Any Python host works (Render, Railway, Fly.io free tiers). Point it at
`backend/main.py`, set the four env vars, expose port 8000/`$PORT`, and update
`frontend/index.html`'s `API_BASE` to the deployed URL.