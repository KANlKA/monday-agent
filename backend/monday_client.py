"""
Thin wrapper around the Monday.com GraphQL v2 API.
Free with a personal API token (Monday.com -> Avatar -> Administration -> API,
or Profile -> Developers -> My Access Tokens on a free/individual account).
"""
import json
import time
import requests

MONDAY_API_URL = "https://api.monday.com/v2"


class MondayClient:
    def __init__(self, api_token=None):
        import os
        self.token = api_token or os.environ["MONDAY_API_TOKEN"]
        self.headers = {
            "Authorization": self.token,
            "Content-Type": "application/json",
            "API-Version": "2024-10",
        }

    def execute(self, query, variables=None, retries=3):
        last_err = None
        for attempt in range(retries):
            resp = requests.post(
                MONDAY_API_URL,
                json={"query": query, "variables": variables or {}},
                headers=self.headers,
                timeout=30,
            )
            if resp.status_code == 429:
                time.sleep(2 * (attempt + 1))
                continue
            data = resp.json()
            if "errors" in data:
                last_err = data["errors"]
                # complexity/rate limit errors -> backoff and retry
                if any("complexity" in str(e).lower() or "limit" in str(e).lower() for e in data["errors"]):
                    time.sleep(2 * (attempt + 1))
                    continue
                raise RuntimeError(data["errors"])
            return data["data"]
        raise RuntimeError(f"Monday API failed after retries: {last_err}")

    # ---- Board / column setup (used by seed_monday.py) ----

    def create_board(self, name, kind="public"):
        q = """
        mutation ($name: String!, $kind: BoardKind!) {
            create_board(board_name: $name, board_kind: $kind) { id }
        }"""
        return self.execute(q, {"name": name, "kind": kind})["create_board"]["id"]

    def create_column(self, board_id, title, column_type):
        q = """
        mutation ($board_id: ID!, $title: String!, $type: ColumnType!) {
            create_column(board_id: $board_id, title: $title, column_type: $type) { id }
        }"""
        return self.execute(q, {"board_id": board_id, "title": title, "type": column_type})["create_column"]["id"]

    def create_item(self, board_id, item_name, column_values: dict):
        q = """
        mutation ($board_id: ID!, $item_name: String!, $column_values: JSON!) {
            create_item(board_id: $board_id, item_name: $item_name, column_values: $column_values) { id }
        }"""
        return self.execute(
            q,
            {
                "board_id": board_id,
                "item_name": item_name,
                "column_values": json.dumps(column_values),
            },
        )["create_item"]["id"]

    # ---- Read (used at runtime by the agent - never hardcode data) ----

    def get_all_items(self, board_id):
        """Paginates through items_page to fetch every item + column value on a board."""
        items = []
        q = """
        query ($board_id: [ID!], $cursor: String) {
            boards(ids: $board_id) {
                items_page(limit: 100, cursor: $cursor) {
                    cursor
                    items {
                        id
                        name
                        column_values { id text value column { title } }
                    }
                }
            }
        }"""
        cursor = None
        while True:
            data = self.execute(q, {"board_id": [board_id], "cursor": cursor})
            boards = data.get("boards") or []
            if not boards:
                break
            page = boards[0]["items_page"]
            items.extend(page["items"])
            cursor = page["cursor"]
            if not cursor:
                break
        return items