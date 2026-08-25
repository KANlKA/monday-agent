"""
ONE-TIME setup script. Reads the two assignment xlsx files and creates
matching boards + columns on Monday.com, then imports every row as an item.

This is the ONLY place raw file data is touched - the running agent
always queries Monday.com live, never these files.

Usage:
    1. Put Deal_funnel_Data.xlsx and Work_Order_Tracker_Data.xlsx in this
       backend/ folder (or edit the paths below).
    2. export MONDAY_API_TOKEN=xxxx   (or put it in a .env file)
    3. python seed_monday.py
    4. Copy the printed board IDs into your .env file.
"""
import os
import time
import pandas as pd
from dotenv import load_dotenv

load_dotenv()

from monday_client import MondayClient  # noqa: E402

DEALS_FILE = "Deal_funnel_Data.xlsx"
WO_FILE = "Work_Order_Tracker_Data.xlsx"

# Monday.com column type per assignment column. Falls back to "text" for
# anything not listed. Extend this if you add columns later.
STATUS_COLUMNS = {
    "Deal Status", "Execution Status", "Invoice Status", "Collection status",
    "Billing Status", "WO Status (billed)", "Closure Probability", "Deal Stage",
}


def col_type_for(colname):
    lc = colname.lower()
    if "date" in lc:
        return "date"
    if colname in STATUS_COLUMNS:
        return "status"
    if any(k in lc for k in ["value", "amount", "quantity", "qty"]):
        return "numbers"
    return "text"


def build_board(monday, board_name, df):
    board_id = monday.create_board(board_name)
    print(f"Created board '{board_name}' -> id {board_id}")
    col_ids = {}
    name_col = df.columns[0]  # first column becomes the item's built-in "name"
    for c in df.columns:
        if c == name_col:
            continue
        ctype = col_type_for(c)
        try:
            cid = monday.create_column(board_id, c, ctype)
        except Exception as e:
            print(f"  column '{c}' ({ctype}) failed ({e}), retrying as text")
            cid = monday.create_column(board_id, c, "text")
            ctype = "text"
        col_ids[c] = (cid, ctype)
        time.sleep(0.25)
    return board_id, name_col, col_ids


def row_to_column_values(row, col_ids):
    values = {}
    for c, (cid, ctype) in col_ids.items():
        v = row.get(c)
        if pd.isna(v) or v == "":
            continue
        if ctype == "date":
            try:
                values[cid] = {"date": pd.to_datetime(v).strftime("%Y-%m-%d")}
            except Exception:
                pass
        elif ctype == "numbers":
            try:
                values[cid] = str(float(v))
            except Exception:
                pass
        elif ctype == "status":
            values[cid] = {"label": str(v)[:75]}  # monday label length guard
        else:
            values[cid] = str(v)[:2000]
    return values


def seed(file_path, board_name, header_row=0):
    df = pd.read_excel(file_path, header=header_row)
    df = df.dropna(how="all")
    name_col = df.columns[0]
    # Drop rows that are stray repeated header rows leaked into the data
    df = df[df[name_col] != name_col]
    df = df.reset_index(drop=True)

    monday = MondayClient()
    board_id, name_col, col_ids = build_board(monday, board_name, df)

    total = len(df)
    for i, row in df.iterrows():
        item_name = str(row[name_col]) if pd.notna(row[name_col]) else f"Row {i}"
        cvs = row_to_column_values(row, col_ids)
        try:
            monday.create_item(board_id, item_name, cvs)
        except Exception as e:
            print(f"  item '{item_name}' failed: {e}")
        if i % 20 == 0:
            print(f"  ...{i}/{total} rows")
        time.sleep(0.2)
    print(f"Done: {board_name} -> board_id = {board_id} ({total} rows)\n")
    return board_id


if __name__ == "__main__":
    assert os.environ.get("MONDAY_API_TOKEN"), "Set MONDAY_API_TOKEN first"

    deals_id = seed(DEALS_FILE, "Deals - Sales Pipeline", header_row=0)
    # The Work Order sheet has a blank first row before the real header row
    wo_id = seed(WO_FILE, "Work Orders - Execution", header_row=1)

    print("Add these to your .env file:")
    print(f"MONDAY_DEALS_BOARD_ID={deals_id}")
    print(f"MONDAY_WORKORDERS_BOARD_ID={wo_id}")