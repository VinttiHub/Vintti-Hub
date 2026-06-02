from __future__ import annotations

import json
import logging
import os
import time
import traceback
from threading import Lock

from flask import Blueprint, jsonify, request
from psycopg2.extras import Json

from db import get_connection
from dashboards.auth import is_editor
from dashboards.datasets import get as get_dataset, list_all as list_datasets
from dashboards.executor import run_dataset, sample_dataset, DatasetError

bp = Blueprint("dashboards", __name__, url_prefix="/dashboards")


# ---------------------------------------------------------------------------
# Chart-data cache (TTL, in-memory per process).
#
# The chart-data endpoint runs a SQL query on every request; a single dashboard
# load fires ~150-250 of them. Dashboard data changes slowly (by the day), so we
# cache the full JSON response keyed by (slug, chart_key, query-args) for a short
# TTL. A cache hit returns WITHOUT opening a DB connection or running SQL — which
# cuts App Runner active-vCPU, RDS CPU credits and latency.
#
# Tune/disable with env vars:
#   DASHBOARD_CACHE_TTL   seconds (default 300). Set 0 to disable.
# Bypass a single request with ?nocache=1.
# ---------------------------------------------------------------------------
_CHART_CACHE: dict = {}
_CHART_CACHE_LOCK = Lock()


def _cache_ttl() -> int:
    try:
        return int(os.environ.get("DASHBOARD_CACHE_TTL", "300"))
    except (TypeError, ValueError):
        return 300


def _cache_key(slug: str, chart_key: str, args: dict) -> tuple:
    items = tuple(sorted((str(k), str(v)) for k, v in args.items()))
    return (slug, chart_key, items)


def _cache_get(key: tuple):
    ttl = _cache_ttl()
    if ttl <= 0:
        return None
    now = time.time()
    with _CHART_CACHE_LOCK:
        entry = _CHART_CACHE.get(key)
        if entry and (now - entry[0]) < ttl:
            return entry[1]
        if entry:
            _CHART_CACHE.pop(key, None)
    return None


def _cache_set(key: tuple, value) -> None:
    if _cache_ttl() <= 0:
        return
    with _CHART_CACHE_LOCK:
        # Cheap bound: clear if it grows unreasonably (filters explosion).
        if len(_CHART_CACHE) > 5000:
            _CHART_CACHE.clear()
        _CHART_CACHE[key] = (time.time(), value)


ALLOWED_CHART_TYPES = {
    "bar", "line", "area", "pie", "donut", "scatter",
    "table", "kpi", "gauge", "funnel", "heatmap", "sankey", "treemap",
}


def _user_email() -> str | None:
    email = request.headers.get("X-User-Email")
    if not email:
        email = request.args.get("user_email")
    return (email or "").strip().lower() or None


def _require_editor():
    if not is_editor(_user_email()):
        return jsonify({"error": "forbidden"}), 403
    return None


def _row_to_dict(cur, row):
    return dict(zip([c[0] for c in cur.description], row))


@bp.route("/me", methods=["GET"])
def me():
    email = _user_email()
    return jsonify({"email": email, "editor": is_editor(email)})


@bp.route("/datasets", methods=["GET"])
def datasets_index():
    return jsonify(list_datasets())


@bp.route("/datasets/<key>/sample", methods=["GET"])
def dataset_sample(key: str):
    try:
        limit = min(int(request.args.get("limit", 20)), 200)
        rows = sample_dataset(key, limit=limit)
        return jsonify({"rows": rows, "count": len(rows)})
    except DatasetError as exc:
        return jsonify({"error": str(exc)}), 404
    except Exception as exc:
        logging.error("dataset_sample failed: %s\n%s", exc, traceback.format_exc())
        return jsonify({"error": str(exc)}), 500


@bp.route("/<slug>", methods=["GET"])
def get_dashboard(slug: str):
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, slug, name, layout_json, version, updated_at, updated_by FROM dashboards WHERE slug = %s",
            (slug,),
        )
        row = cur.fetchone()
        if not row:
            return jsonify({"error": "not_found"}), 404
        dashboard = _row_to_dict(cur, row)

        cur.execute(
            """
            SELECT id, chart_key, tab_key, title, type, dataset_key, config_json,
                   position_json, sort_order, updated_at
            FROM dashboard_charts
            WHERE dashboard_id = %s
            ORDER BY tab_key, sort_order, id
            """,
            (dashboard["id"],),
        )
        charts = [_row_to_dict(cur, r) for r in cur.fetchall()]
        cur.close()
        return jsonify({"dashboard": dashboard, "charts": charts})
    finally:
        conn.close()


@bp.route("/<slug>/charts/<chart_key>/data", methods=["GET"])
def get_chart_data(slug: str, chart_key: str):
    # Build a stable cache key from the query args (config-level filters are
    # static per chart_key, so request args fully determine the variant).
    args = request.args.to_dict(flat=True)
    args.pop("user_email", None)
    nocache = str(args.pop("nocache", "")).strip() in ("1", "true", "yes")
    ckey = _cache_key(slug, chart_key, args)
    if not nocache:
        cached = _cache_get(ckey)
        if cached is not None:
            return jsonify(cached)

    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT c.dataset_key, c.config_json
            FROM dashboard_charts c
            JOIN dashboards d ON d.id = c.dashboard_id
            WHERE d.slug = %s AND c.chart_key = %s
            """,
            (slug, chart_key),
        )
        row = cur.fetchone()
        cur.close()
        if not row:
            return jsonify({"error": "chart_not_found"}), 404

        dataset_key, config_json = row
        config = config_json if isinstance(config_json, dict) else json.loads(config_json or "{}")

        filters = {**(config.get("filters") or {}), **request.args.to_dict(flat=True)}
        if "user_email" in filters:
            filters.pop("user_email")

        rows = run_dataset(dataset_key, filters=filters)
        result = {"rows": rows, "meta": {"dataset": dataset_key, "count": len(rows)}}
        if not nocache:
            _cache_set(ckey, result)
        return jsonify(result)
    except DatasetError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        logging.error("chart_data failed: %s\n%s", exc, traceback.format_exc())
        return jsonify({"error": str(exc)}), 500
    finally:
        conn.close()


def _validate_chart_payload(payload: dict) -> tuple[dict | None, str | None]:
    if not isinstance(payload, dict):
        return None, "invalid body"
    chart_type = (payload.get("type") or "").strip()
    if chart_type not in ALLOWED_CHART_TYPES:
        return None, f"invalid chart type '{chart_type}'"
    dataset_key = (payload.get("dataset_key") or "").strip()
    if not get_dataset(dataset_key):
        return None, f"invalid dataset '{dataset_key}'"
    chart_key = (payload.get("chart_key") or "").strip()
    if not chart_key:
        return None, "chart_key required"
    title = (payload.get("title") or "").strip() or chart_key
    tab_key = (payload.get("tab_key") or "default").strip() or "default"

    cleaned = {
        "chart_key": chart_key,
        "tab_key": tab_key,
        "title": title,
        "type": chart_type,
        "dataset_key": dataset_key,
        "config_json": payload.get("config") or payload.get("config_json") or {},
        "position_json": payload.get("position") or payload.get("position_json") or {},
        "sort_order": int(payload.get("sort_order") or 0),
    }
    if not isinstance(cleaned["config_json"], dict) or not isinstance(cleaned["position_json"], dict):
        return None, "config and position must be objects"
    return cleaned, None


@bp.route("/<slug>/charts", methods=["POST"])
def create_chart(slug: str):
    forbidden = _require_editor()
    if forbidden:
        return forbidden

    cleaned, err = _validate_chart_payload(request.get_json(silent=True) or {})
    if err:
        return jsonify({"error": err}), 400

    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT id FROM dashboards WHERE slug = %s", (slug,))
        row = cur.fetchone()
        if not row:
            cur.close()
            return jsonify({"error": "dashboard_not_found"}), 404
        dashboard_id = row[0]

        cur.execute(
            """
            INSERT INTO dashboard_charts
              (dashboard_id, chart_key, tab_key, title, type, dataset_key,
               config_json, position_json, sort_order)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (dashboard_id, chart_key) DO UPDATE SET
              tab_key = EXCLUDED.tab_key,
              title = EXCLUDED.title,
              type = EXCLUDED.type,
              dataset_key = EXCLUDED.dataset_key,
              config_json = EXCLUDED.config_json,
              position_json = EXCLUDED.position_json,
              sort_order = EXCLUDED.sort_order,
              updated_at = NOW()
            RETURNING id
            """,
            (
                dashboard_id,
                cleaned["chart_key"],
                cleaned["tab_key"],
                cleaned["title"],
                cleaned["type"],
                cleaned["dataset_key"],
                Json(cleaned["config_json"]),
                Json(cleaned["position_json"]),
                cleaned["sort_order"],
            ),
        )
        chart_id = cur.fetchone()[0]
        conn.commit()
        cur.close()
        return jsonify({"id": chart_id, **cleaned})
    except Exception as exc:
        conn.rollback()
        logging.error("create_chart failed: %s\n%s", exc, traceback.format_exc())
        return jsonify({"error": str(exc)}), 500
    finally:
        conn.close()


@bp.route("/<slug>/charts/<int:chart_id>", methods=["PATCH"])
def update_chart(slug: str, chart_id: int):
    forbidden = _require_editor()
    if forbidden:
        return forbidden

    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict) or not payload:
        return jsonify({"error": "empty patch"}), 400

    updatable = {
        "title": str,
        "type": str,
        "dataset_key": str,
        "tab_key": str,
        "chart_key": str,
        "sort_order": int,
    }
    sets: list[str] = []
    values: list = []
    for key, caster in updatable.items():
        if key in payload:
            val = payload[key]
            if key == "type" and val not in ALLOWED_CHART_TYPES:
                return jsonify({"error": f"invalid type '{val}'"}), 400
            if key == "dataset_key" and not get_dataset(val):
                return jsonify({"error": f"invalid dataset '{val}'"}), 400
            sets.append(f"{key} = %s")
            values.append(caster(val))

    for jkey in ("config", "position"):
        pkey = f"{jkey}_json"
        if jkey in payload or pkey in payload:
            v = payload.get(jkey) if jkey in payload else payload.get(pkey)
            if not isinstance(v, dict):
                return jsonify({"error": f"{jkey} must be object"}), 400
            sets.append(f"{pkey} = %s")
            values.append(Json(v))

    if not sets:
        return jsonify({"error": "nothing to update"}), 400

    sets.append("updated_at = NOW()")
    values.extend([slug, chart_id])

    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            f"""
            UPDATE dashboard_charts
               SET {', '.join(sets)}
             WHERE id = %s
               AND dashboard_id = (SELECT id FROM dashboards WHERE slug = %s)
            """,
            (*values[:-2], values[-1], values[-2]),
        )
        updated = cur.rowcount
        conn.commit()
        cur.close()
        if not updated:
            return jsonify({"error": "not_found"}), 404
        return jsonify({"ok": True})
    except Exception as exc:
        conn.rollback()
        logging.error("update_chart failed: %s\n%s", exc, traceback.format_exc())
        return jsonify({"error": str(exc)}), 500
    finally:
        conn.close()


@bp.route("/<slug>/charts/<int:chart_id>", methods=["DELETE"])
def delete_chart(slug: str, chart_id: int):
    forbidden = _require_editor()
    if forbidden:
        return forbidden

    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            DELETE FROM dashboard_charts
             WHERE id = %s
               AND dashboard_id = (SELECT id FROM dashboards WHERE slug = %s)
            """,
            (chart_id, slug),
        )
        deleted = cur.rowcount
        conn.commit()
        cur.close()
        if not deleted:
            return jsonify({"error": "not_found"}), 404
        return jsonify({"ok": True})
    except Exception as exc:
        conn.rollback()
        return jsonify({"error": str(exc)}), 500
    finally:
        conn.close()


@bp.route("/<slug>", methods=["PATCH"])
def update_dashboard(slug: str):
    forbidden = _require_editor()
    if forbidden:
        return forbidden

    payload = request.get_json(silent=True) or {}
    sets: list[str] = []
    values: list = []

    if "name" in payload:
        sets.append("name = %s")
        values.append(str(payload["name"]))
    if "layout" in payload or "layout_json" in payload:
        v = payload.get("layout") if "layout" in payload else payload.get("layout_json")
        if not isinstance(v, dict):
            return jsonify({"error": "layout must be object"}), 400
        sets.append("layout_json = %s")
        values.append(Json(v))

    if not sets:
        return jsonify({"error": "nothing to update"}), 400

    sets.append("updated_at = NOW()")
    sets.append("version = version + 1")
    sets.append("updated_by = %s")
    values.append(_user_email())
    values.append(slug)

    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            f"UPDATE dashboards SET {', '.join(sets)} WHERE slug = %s RETURNING version",
            tuple(values),
        )
        row = cur.fetchone()
        conn.commit()
        cur.close()
        if not row:
            return jsonify({"error": "not_found"}), 404
        return jsonify({"ok": True, "version": row[0]})
    except Exception as exc:
        conn.rollback()
        logging.error("update_dashboard failed: %s\n%s", exc, traceback.format_exc())
        return jsonify({"error": str(exc)}), 500
    finally:
        conn.close()
