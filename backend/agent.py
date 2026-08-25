"""
Query understanding + business intelligence layer.

Design: Claude drives a tool-use loop. Python (not the LLM) does all
aggregation/math over pandas DataFrames pulled live from Monday.com -
this keeps numbers trustworthy and avoids the LLM hallucinating sums.
Claude's job is: interpret the founder's question, decide which tool
calls answer it, and turn the results into a clear, honest narrative
(including data-quality caveats).
"""
import os
import json
from groq import Groq
import pandas as pd

from monday_client import MondayClient
from data_tools import items_to_dataframe, clean_deals, clean_work_orders, data_quality_report

client = Groq(api_key=os.environ["GROQ_API_KEY"])
MODEL = "llama-3.3-70b-versatile"
monday = MondayClient()

DEALS_BOARD_ID = os.environ["MONDAY_DEALS_BOARD_ID"]
WO_BOARD_ID = os.environ["MONDAY_WORKORDERS_BOARD_ID"]

_cache = {"deals": None, "wo": None}


def load_data(force=False):
    if _cache["deals"] is None or force:
        _cache["deals"] = clean_deals(items_to_dataframe(monday.get_all_items(DEALS_BOARD_ID)))
    if _cache["wo"] is None or force:
        _cache["wo"] = clean_work_orders(items_to_dataframe(monday.get_all_items(WO_BOARD_ID)))
    return _cache["deals"], _cache["wo"]


def _filter(df, filters):
    out = df
    for col, val in filters.items():
        if val and col in out.columns:
            out = out[out[col].astype(str).str.contains(str(val), case=False, na=False)]
    return out


TOOLS_RAW = [
    {
        "name": "query_deals",
        "description": "Filter and summarize the Deals board (sales pipeline). Returns row count, total pipeline value, an optional breakdown, and sample rows. Use this for revenue pipeline, sector performance, deal stage/status questions.",
        "input_schema": {
            "type": "object",
            "properties": {
                "sector": {"type": "string", "description": "e.g. Mining, Powerline, Renewables, Aviation, Railways"},
                "deal_status": {"type": "string", "description": "Open, Won, Dead, On Hold"},
                "deal_stage": {"type": "string", "description": "e.g. 'B. Sales Qualified Leads', 'F. Negotiations'"},
                "owner_code": {"type": "string"},
                "group_by": {
                    "type": "string",
                    "description": "One of: Sector/service, Deal Status, Deal Stage, Owner code, Closure Probability - sums deal value per group",
                },
            },
        },
    },
    {
        "name": "query_work_orders",
        "description": "Filter and summarize the Work Orders board (execution + billing). Returns row count, sums of billed/collected/receivable amounts, and sample rows. Use this for revenue collected, receivables, execution status, operational questions.",
        "input_schema": {
            "type": "object",
            "properties": {
                "sector": {"type": "string"},
                "execution_status": {"type": "string", "description": "e.g. Completed, Not Started, Executed until current month"},
                "group_by": {
                    "type": "string",
                    "description": "One of: Sector, Execution Status, Type of Work - sums receivable amount per group",
                },
            },
        },
    },
    {
        "name": "cross_reference_deal",
        "description": "Look up a deal by (partial) name across BOTH boards to connect pipeline status with execution/billing reality for that client.",
        "input_schema": {
            "type": "object",
            "properties": {"deal_name": {"type": "string"}},
            "required": ["deal_name"],
        },
    },
    {
        "name": "data_quality_report",
        "description": "Get missing-data statistics for a board, so caveats can be communicated honestly instead of silently ignored.",
        "input_schema": {
            "type": "object",
            "properties": {"board": {"type": "string", "enum": ["deals", "work_orders"]}},
            "required": ["board"],
        },
    },
    {
        "name": "generate_leadership_update",
        "description": "Produce the raw numbers needed for a leadership/board-style update: pipeline by stage, won vs lost, revenue collected vs receivable, top data-quality risks. Call this when the founder asks for a summary, update, or report to share with leadership.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "refresh_data",
        "description": "Force a fresh pull from Monday.com. Use only if the user explicitly asks for the latest/live data.",
        "input_schema": {"type": "object", "properties": {}},
    },
]

# Groq/OpenAI-style function tool format
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": t["name"],
            "description": t["description"],
            "parameters": t["input_schema"],
        },
    }
    for t in TOOLS_RAW
]


def run_tool(name, inp):
    deals, wo = load_data()

    if name == "query_deals":
        colmap = {
            "sector": "Sector/service",
            "deal_status": "Deal Status",
            "deal_stage": "Deal Stage",
            "owner_code": "Owner code",
        }
        filt = {colmap[k]: v for k, v in inp.items() if k in colmap and v}
        sub = _filter(deals, filt)
        result = {
            "row_count": len(sub),
            "total_deal_value": float(sub["Masked Deal value"].sum(skipna=True)) if "Masked Deal value" in sub else None,
            "sample": sub.head(8).fillna("").to_dict(orient="records"),
        }
        gb = inp.get("group_by")
        if gb and gb in sub.columns:
            result[f"sum_by_{gb}"] = sub.groupby(gb)["Masked Deal value"].sum(min_count=1).fillna(0).round(0).to_dict()
        return result

    if name == "query_work_orders":
        filt = {}
        if inp.get("sector"):
            filt["Sector"] = inp["sector"]
        if inp.get("execution_status"):
            filt["Execution Status"] = inp["execution_status"]
        sub = _filter(wo, filt)
        money_cols = [c for c in sub.columns if any(k in c for k in ["Amount", "Billed", "Collected"])]
        sums = {c: round(float(sub[c].sum(skipna=True)), 0) for c in money_cols}
        result = {"row_count": len(sub), "sums": sums, "sample": sub.head(8).fillna("").to_dict(orient="records")}
        gb = inp.get("group_by")
        if gb and gb in sub.columns and "Amount Receivable (Masked)" in sub.columns:
            result[f"receivable_by_{gb}"] = (
                sub.groupby(gb)["Amount Receivable (Masked)"].sum(min_count=1).fillna(0).round(0).to_dict()
            )
        return result

    if name == "cross_reference_deal":
        needle = inp["deal_name"]
        d_match = deals[deals["Deal Name"].astype(str).str.contains(needle, case=False, na=False)] if "Deal Name" in deals.columns else pd.DataFrame()
        w_match = wo[wo["Deal name masked"].astype(str).str.contains(needle, case=False, na=False)] if "Deal name masked" in wo.columns else pd.DataFrame()
        return {
            "deals_matches": d_match.fillna("").to_dict(orient="records"),
            "work_order_matches": w_match.fillna("").to_dict(orient="records"),
        }

    if name == "data_quality_report":
        df = deals if inp.get("board") == "deals" else wo
        return data_quality_report(df, inp.get("board"))

    if name == "generate_leadership_update":
        pipeline_by_stage = deals.groupby("Deal Stage")["Masked Deal value"].sum(min_count=1).fillna(0).round(0).to_dict()
        won = deals[deals["Deal Status"] == "Won"]["Masked Deal value"].sum(skipna=True)
        dead = deals[deals["Deal Status"] == "Dead"]["Masked Deal value"].sum(skipna=True)
        open_val = deals[deals["Deal Status"] == "Open"]["Masked Deal value"].sum(skipna=True)
        collected = wo["Collected Amount in Rupees (Incl of GST.) (Masked)"].sum(skipna=True) if "Collected Amount in Rupees (Incl of GST.) (Masked)" in wo else None
        receivable = wo["Amount Receivable (Masked)"].sum(skipna=True) if "Amount Receivable (Masked)" in wo else None
        exec_status_counts = wo["Execution Status"].value_counts(dropna=True).to_dict()
        return {
            "pipeline_value_by_stage": pipeline_by_stage,
            "won_value": round(float(won), 0),
            "dead_value": round(float(dead), 0),
            "open_pipeline_value": round(float(open_val), 0),
            "total_collected": round(float(collected), 0) if collected is not None else None,
            "total_receivable": round(float(receivable), 0) if receivable is not None else None,
            "execution_status_breakdown": exec_status_counts,
            "deals_data_quality": data_quality_report(deals, "deals"),
            "work_orders_data_quality": data_quality_report(wo, "work_orders"),
        }

    if name == "refresh_data":
        load_data(force=True)
        return {"status": "refreshed"}

    return {"error": f"unknown tool {name}"}


SYSTEM_PROMPT = """You are Skylark Drones' internal Business Intelligence assistant, built for founders and executives.
You answer questions using two live Monday.com boards: Deals (sales pipeline) and Work Orders (execution + billing).

Rules:
- Always call a tool to get real numbers. Never invent or estimate figures yourself.
- This data is real-world messy (missing values, inconsistent labels). When a field you relied on has significant
  gaps (check data_quality_report or the significant_gaps you're given), state that caveat briefly and plainly -
  don't hide it, but don't over-explain it either.
- Lead with a direct, founder-level answer (a number or a clear verdict) in the first sentence or two.
  Follow with 2-4 short bullets of supporting context or risk flags. Avoid dumping raw tables unless asked.
- If a query is ambiguous (e.g. "this quarter", "recent"), state the assumption you're using in one line and
  proceed - don't block on a clarifying question unless you genuinely cannot produce a useful answer without it.
- All currency figures are masked/anonymized but internally consistent - relative comparisons and totals are valid.
- When asked for a "leadership update" / "summary for the board" / "leadership report", call generate_leadership_update
  and write it as a short, scannable brief (headline numbers, then bullets), not a wall of text.
"""


def chat(messages):
    """messages: running conversation as OpenAI/Groq-style message list (no system message
    included - it's added here). Returns (answer_text, updated_messages)."""
    full = [{"role": "system", "content": SYSTEM_PROMPT}] + messages
    while True:
        resp = client.chat.completions.create(
            model=MODEL,
            max_tokens=2000,
            tools=TOOLS,
            messages=full,
        )
        msg = resp.choices[0].message
        full.append({"role": "assistant", "content": msg.content, "tool_calls": msg.tool_calls})

        if not msg.tool_calls:
            # strip the system message before handing history back to the caller
            return msg.content, full[1:]

        for tc in msg.tool_calls:
            try:
                args = json.loads(tc.function.arguments or "{}")
                result = run_tool(tc.function.name, args)
            except Exception as e:
                result = {"error": str(e)}
            full.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": json.dumps(result, default=str),
                }
            )