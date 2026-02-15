from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple

from psycopg2.extras import RealDictCursor

BOGOTA_TZ = timezone(timedelta(hours=-5))


def _today_bogota() -> date:
    return datetime.now(BOGOTA_TZ).date()


def _normalize_stage(stage: Optional[str]) -> str:
    return (stage or "").strip().lower()


def _format_role_client(position: Optional[str], client: Optional[str]) -> Tuple[str, str, str]:
    role = (position or "").strip() or "role"
    client_name = (client or "").strip() or "client"
    label = f"{role} at {client_name}"
    return role, client_name, label


def _fetch_hr_lead_user(cur: RealDictCursor, hr_lead_email: Optional[str]) -> Optional[Dict[str, Any]]:
    if not hr_lead_email:
        return None
    cur.execute(
        """
        SELECT user_id, user_name, email_vintti
        FROM users
        WHERE LOWER(email_vintti) = LOWER(%s)
          AND LOWER(COALESCE(role, '')) LIKE 'hr lead%%'
        LIMIT 1
        """,
        (hr_lead_email,),
    )
    return cur.fetchone()


def _fetch_opportunity_context(cur: RealDictCursor, opportunity_id: int) -> Optional[Dict[str, Any]]:
    cur.execute(
        """
        SELECT
          o.opportunity_id,
          o.opp_position_name,
          o.opp_stage,
          o.opp_hr_lead,
          o.replacement_of,
          COALESCE(
            o.since_sourcing,
            (SELECT MAX(s.since_sourcing) FROM sourcing s WHERE s.opportunity_id = o.opportunity_id)
          ) AS since_sourcing,
          a.client_name
        FROM opportunity o
        LEFT JOIN account a ON a.account_id = o.account_id
        WHERE o.opportunity_id = %s
        LIMIT 1
        """,
        (opportunity_id,),
    )
    return cur.fetchone()


def _get_next_todo_id(cur: RealDictCursor, cache: Dict[str, Any]) -> int:
    if cache.get("next_id") is None:
        cur.execute("SELECT COALESCE(MAX(to_do_id), 0) + 1 AS next_id FROM to_do")
        cache["next_id"] = cur.fetchone()["next_id"]
    next_id = cache["next_id"]
    cache["next_id"] += 1
    return next_id


def _get_next_order(cur: RealDictCursor, cache: Dict[str, Any], user_id: int, subtask: Optional[int]) -> int:
    key = (user_id, subtask)
    if key not in cache:
        cur.execute(
            """
            SELECT COALESCE(MAX(orden), 0) + 1 AS next_order
            FROM to_do
            WHERE user_id = %s AND (
              (subtask IS NULL AND %s IS NULL)
              OR subtask = %s
            )
            """,
            (user_id, subtask, subtask),
        )
        cache[key] = cur.fetchone()["next_order"]
    next_order = cache[key]
    cache[key] += 1
    return next_order


def _todo_exists(
    cur: RealDictCursor,
    user_id: int,
    description: str,
    due_date: Optional[date],
    dedupe_by_due_date: bool,
) -> bool:
    if dedupe_by_due_date:
        cur.execute(
            "SELECT 1 FROM to_do WHERE user_id = %s AND description = %s AND due_date = %s LIMIT 1",
            (user_id, description, due_date),
        )
    else:
        cur.execute(
            "SELECT 1 FROM to_do WHERE user_id = %s AND description = %s LIMIT 1",
            (user_id, description),
        )
    return cur.fetchone() is not None


def _ensure_todo(
    cur: RealDictCursor,
    cache: Dict[str, Any],
    user_id: int,
    description: str,
    due_date: Optional[date],
    dedupe_by_due_date: bool = True,
    subtask: Optional[int] = None,
) -> bool:
    if _todo_exists(cur, user_id, description, due_date, dedupe_by_due_date):
        return False

    to_do_id = _get_next_todo_id(cur, cache)
    orden = _get_next_order(cur, cache.setdefault("order", {}), user_id, subtask)
    cur.execute(
        """
        INSERT INTO to_do (to_do_id, user_id, description, due_date, "check", orden, subtask)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        """,
        (to_do_id, user_id, description, due_date, False, orden, subtask),
    )
    return True


def create_stage_todos(cur: RealDictCursor, opportunity_id: int, new_stage: str, today: Optional[date] = None) -> int:
    ctx = _fetch_opportunity_context(cur, opportunity_id)
    if not ctx:
        return 0

    user = _fetch_hr_lead_user(cur, ctx.get("opp_hr_lead"))
    if not user:
        return 0

    today = today or _today_bogota()
    due_7 = today + timedelta(days=7)
    due_2 = today + timedelta(days=2)

    _, _, label = _format_role_client(ctx.get("opp_position_name"), ctx.get("client_name"))
    stage_norm = _normalize_stage(new_stage)

    descriptions = []
    if "sourc" in stage_norm:
        descriptions.append((f"Source candidates for the {label}. Due in 7 days.", due_7))
    if "deep" in stage_norm:
        descriptions.append((f"Draft the job description for the {label}. Due in 7 days.", due_7))
    if "negotiat" in stage_norm:
        descriptions.append((f"Do we already have references for the {label}? Due in 7 days.", due_7))
    if "close win" in stage_norm or "closed lost" in stage_norm or "close lost" in stage_norm:
        descriptions.append((f"Remove the {label} from the career site. Due in 2 days.", due_2))

    if not descriptions:
        return 0

    cache: Dict[str, Any] = {}
    created = 0
    for description, due_date in descriptions:
        if _ensure_todo(cur, cache, user["user_id"], description, due_date, dedupe_by_due_date=True):
            created += 1
    return created


def create_assignment_todo(
    cur: RealDictCursor,
    opportunity_id: int,
    hr_lead_email: Optional[str],
    today: Optional[date] = None,
) -> int:
    user = _fetch_hr_lead_user(cur, hr_lead_email)
    if not user:
        return 0

    ctx = _fetch_opportunity_context(cur, opportunity_id)
    if not ctx:
        return 0

    today = today or _today_bogota()
    due_2 = today + timedelta(days=2)

    _, _, label = _format_role_client(ctx.get("opp_position_name"), ctx.get("client_name"))
    description = f"Post the {label} on the career site. Due in 2 days."

    cache: Dict[str, Any] = {}
    return int(_ensure_todo(cur, cache, user["user_id"], description, due_2, dedupe_by_due_date=True))


def create_replacement_todo(cur: RealDictCursor, opportunity_id: int, today: Optional[date] = None) -> int:
    ctx = _fetch_opportunity_context(cur, opportunity_id)
    if not ctx or not ctx.get("replacement_of"):
        return 0

    user = _fetch_hr_lead_user(cur, ctx.get("opp_hr_lead"))
    if not user:
        return 0

    today = today or _today_bogota()
    due_2 = today + timedelta(days=2)

    _, _, label = _format_role_client(ctx.get("opp_position_name"), ctx.get("client_name"))
    description = (
        f"Schedule two back-to-back turbo interviews (e.g., Monday and Tuesday) "
        f"for the {label}. Due in 2 days."
    )

    cache: Dict[str, Any] = {}
    return int(_ensure_todo(cur, cache, user["user_id"], description, due_2, dedupe_by_due_date=True))


def run_scheduled_todos(cur: RealDictCursor, today: Optional[date] = None) -> Dict[str, int]:
    today = today or _today_bogota()
    due_7 = today + timedelta(days=7)
    due_2 = today + timedelta(days=2)
    weekday = today.weekday()
    should_run_weekly = weekday in (0, 4)

    cur.execute(
        """
        SELECT
          o.opportunity_id,
          o.opp_position_name,
          o.opp_stage,
          o.opp_hr_lead,
          COALESCE(
            o.since_sourcing,
            (SELECT MAX(s.since_sourcing) FROM sourcing s WHERE s.opportunity_id = o.opportunity_id)
          ) AS since_sourcing,
          a.client_name,
          u.user_id
        FROM opportunity o
        JOIN users u ON LOWER(u.email_vintti) = LOWER(o.opp_hr_lead)
        LEFT JOIN account a ON a.account_id = o.account_id
        WHERE o.opp_hr_lead IS NOT NULL
          AND LOWER(COALESCE(u.role, '')) LIKE 'hr lead%%'
        """,
    )
    opportunities = cur.fetchall() or []

    cur.execute(
        """
        SELECT DISTINCT oc.opportunity_id
        FROM opportunity_candidates oc
        WHERE LOWER(COALESCE(oc.stage_pipeline, '')) LIKE 'no avanza%%'
        """,
    )
    no_advance_opps = {row["opportunity_id"] for row in (cur.fetchall() or [])}

    cache: Dict[str, Any] = {}
    created = {
        "sourcing_day_3": 0,
        "sourcing_day_15": 0,
        "pipeline_statuses": 0,
        "interview_counts": 0,
        "no_advance_signoff": 0,
    }

    for opp in opportunities:
        stage_norm = _normalize_stage(opp.get("opp_stage"))
        if stage_norm in ("close win", "closed lost"):
            continue

        _, _, label = _format_role_client(opp.get("opp_position_name"), opp.get("client_name"))
        since_sourcing = opp.get("since_sourcing")
        if isinstance(since_sourcing, datetime):
            since_sourcing = since_sourcing.date()

        if "sourc" in stage_norm and since_sourcing:
            try:
                days_since = (today - since_sourcing).days
            except Exception:
                days_since = None
            if days_since == 3:
                description = (
                    f"Sourcing day 3 check-in for the {label} (since {since_sourcing}): "
                    "do we have a candidate? Due in 7 days."
                )
                if _ensure_todo(cur, cache, opp["user_id"], description, due_7, dedupe_by_due_date=True):
                    created["sourcing_day_3"] += 1
            if days_since is not None and days_since >= 15:
                description = (
                    f"Sourcing has been open for 15+ days for the {label} (since {since_sourcing}). "
                    "Please check in with the recruiter and add context. Due in 7 days."
                )
                if _ensure_todo(cur, cache, opp["user_id"], description, due_7, dedupe_by_due_date=False):
                    created["sourcing_day_15"] += 1

        if should_run_weekly:
            description = f"Update all pipeline statuses for the {label}. Due in 2 days."
            if _ensure_todo(cur, cache, opp["user_id"], description, due_2, dedupe_by_due_date=True):
                created["pipeline_statuses"] += 1

            description = f"Update all interview counts for the {label}. Due in 2 days."
            if _ensure_todo(cur, cache, opp["user_id"], description, due_2, dedupe_by_due_date=True):
                created["interview_counts"] += 1

            if opp["opportunity_id"] in no_advance_opps:
                description = (
                    "Send sign-off to candidates marked as 'No avanza' for the "
                    f"{label}. Due in 2 days."
                )
                if _ensure_todo(cur, cache, opp["user_id"], description, due_2, dedupe_by_due_date=True):
                    created["no_advance_signoff"] += 1

    return created
