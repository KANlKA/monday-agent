"""
Converts raw Monday.com items into cleaned pandas DataFrames.
Handles the real-world mess in this dataset:
- Stray header rows that leaked in as data rows
- Blank / "None" / "nan" strings instead of real nulls
- Inconsistent numeric and date formatting
- Whitespace-padded category labels (sector, status, stage)
"""
import pandas as pd

NULL_LIKE = {"", "None", "none", "nan", "NaN", "N/A", "n/a", "-"}


def items_to_dataframe(items):
    rows = []
    for it in items:
        row = {"__item_name": it["name"], "__item_id": it["id"]}
        for cv in it["column_values"]:
            title = cv["column"]["title"]
            row[title] = cv["text"]
        rows.append(row)
    return pd.DataFrame(rows)


def _drop_stray_header_rows(df, header_like_cols):
    """Some rows in the source data are literally the header row repeated
    (e.g. a 'Deal Status' cell containing the text 'Deal Status'). Drop them."""
    mask = pd.Series(True, index=df.index)
    for c in header_like_cols:
        if c in df.columns:
            mask &= df[c] != c
    return df[mask]


def _clean_text_col(df, col):
    if col in df.columns:
        cleaned = df[col].astype(str).str.strip()
        cleaned = cleaned.where(~cleaned.isin(NULL_LIKE), None)
        df[col] = cleaned
    return df


def clean_deals(df):
    df = df.copy()
    df = _drop_stray_header_rows(df, ["Deal Status", "Deal Stage", "Closure Probability", "Product deal"])
    for c in ["Deal Status", "Deal Stage", "Sector/service", "Closure Probability", "Product deal", "Owner code", "Client Code"]:
        df = _clean_text_col(df, c)
    if "Masked Deal value" in df.columns:
        df["Masked Deal value"] = pd.to_numeric(df["Masked Deal value"], errors="coerce")
    for c in ["Close Date (A)", "Tentative Close Date", "Created Date"]:
        if c in df.columns:
            df[c] = pd.to_datetime(df[c], errors="coerce")
    return df.reset_index(drop=True)


def clean_work_orders(df):
    df = df.copy()
    df = _drop_stray_header_rows(df, ["Execution Status", "Sector", "Invoice Status"])
    money_cols = [c for c in df.columns if any(k in c for k in ["Amount", "Billed", "Collected", "Value"])]
    for c in money_cols:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    date_cols = [c for c in df.columns if "date" in c.lower()]
    for c in date_cols:
        df[c] = pd.to_datetime(df[c], errors="coerce")
    for c in ["Sector", "Execution Status", "Type of Work", "Nature of Work", "Invoice Status",
              "Collection status", "Billing Status", "WO Status (billed)", "BD/KAM Personnel code"]:
        df = _clean_text_col(df, c)
    return df.reset_index(drop=True)


def data_quality_report(df, name):
    """Summarizes missingness so the agent can surface honest caveats instead
    of silently ignoring gaps."""
    total = len(df)
    report = {"board": name, "total_rows": total, "significant_gaps": {}}
    if total == 0:
        return report
    for c in df.columns:
        if c.startswith("__"):
            continue
        nulls = df[c].isna().sum()
        pct = round(100 * nulls / total, 1)
        if pct >= 15:
            report["significant_gaps"][c] = f"{pct}% missing ({nulls}/{total} rows)"
    return report