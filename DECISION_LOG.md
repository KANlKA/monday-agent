# Decision Log

## Key assumptions
- **Column typing on import**: Monday.com column types (date/numbers/status/text) were
  inferred from column names (`*date*` → date, `*Amount|Value|Quantity*` → numbers,
  known status-like fields → status, else text). Not hand-verified per column against
  what a Skylark ops person would actually want — good enough for querying, would
  refine with domain input.
- **"This quarter" / relative time questions**: the data has no single obvious fiscal
  calendar column. The agent states its assumption (e.g. which date field/window it
  used) inline rather than blocking with a clarifying question, per the assignment's
  guidance to proceed under ambiguity.
- **Deal Name → Work Order linkage**: the two boards share a "deal name" style field
  but no formal foreign key. `cross_reference_deal` does a fuzzy text match, which is
  workable for this dataset but not a real join key — a real implementation would need
  a shared deal ID.
- **Masked/anonymized figures**: treated as internally consistent for relative
  comparisons and totals, not as real currency to sanity-check externally.
- **Monday.com "free" tier**: used the standard GraphQL API with a personal token
  (no cost). Seat/board limits on a free account may cap total items if this were
  scaled beyond the assignment dataset.

## Trade-offs chosen and why
- **Python-computed aggregates, LLM for narrative** (not "give Claude the whole
  dataset and let it compute"): more tokens/engineering up front, but numbers are
  computed deterministically in pandas rather than risking LLM arithmetic errors —
  important for a tool founders will trust for revenue figures.
- **In-memory cache + session store** instead of a database: fine for a 6-hour
  prototype; not durable across restarts or multiple instances. Flagged as the first
  thing to fix for real use.
- **Minimal frontend**: prioritized backend correctness (data cleaning, tool design,
  query accuracy) over UI polish, per explicit instruction to build the core first.
- **Tool-use loop over a rigid intent classifier**: gives the agent room to combine
  boards or ask multiple sub-questions per turn, at the cost of being less
  predictable/testable than a fixed set of intents.

## What I'd do differently with more time
- Real deal-ID join between boards instead of fuzzy name matching.
- Persist conversation state and cached data (Redis/Postgres) instead of in-memory.
- Add automated tests around `data_tools.py` cleaning functions using known-bad rows
  from this dataset (stray headers, blank amounts, mixed-case sectors).
- Surface a lightweight "sources" trace in the UI (which tool calls/filters produced
  an answer) for founder trust/auditability.
- Proper fiscal calendar config instead of letting the LLM guess "this quarter."

## Interpretation of "prepare data for leadership updates"
Implemented as a dedicated `generate_leadership_update` tool + `/leadership-summary`
endpoint: pulls pipeline value by stage, won/lost/open totals, revenue collected vs.
outstanding receivable, execution status breakdown, and the current top data-quality
gaps on both boards — then has Claude write it as a short, scannable brief (headline
numbers first, then bullets) rather than a raw data dump. The goal was something a
founder could paste into a board update with minimal editing, while still being
explicit about what's shaky in the underlying data.