from __future__ import annotations

import datetime
from decimal import Decimal

from db import get_connection
from dashboards.datasets import get as get_dataset


class DatasetError(Exception):
    pass


def _jsonable(v):
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, (datetime.date, datetime.datetime)):
        return v.isoformat()
    return v


def run_dataset(dataset_key: str, filters: dict | None = None, limit: int = 5000) -> list[dict]:
    dataset = get_dataset(dataset_key)
    if not dataset:
        raise DatasetError(f"Unknown dataset '{dataset_key}'")

    sql, params = dataset["query"](filters or {})

    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(sql, params)
        cols = [c[0] for c in cur.description]
        rows = cur.fetchall()
        out = [
            {col: _jsonable(val) for col, val in zip(cols, row)}
            for row in rows[:limit]
        ]
        cur.close()
        return out
    finally:
        conn.close()


def sample_dataset(dataset_key: str, limit: int = 20) -> list[dict]:
    return run_dataset(dataset_key, filters={}, limit=limit)
