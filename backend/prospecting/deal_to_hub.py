"""Negocio de Prospecting -> cuenta y oportunidad del hub (2026-11-04).

La misma regla que hoy aplica el sync de HubSpot (`_process_hubspot_deal` en
`routes/hubspot_routes.py`), pero para los negocios que nacen en el Hub:

  * **SQL** -> crea o vincula la CUENTA del CRM (`account`) y sella `account.sql_date`
    una sola vez (las 16 cards de SQL del tab Sales anclan ahí). Vintti AI -> `vintti_ai`.
  * **Deep Dive o más** -> crea la OPORTUNIDAD (Role to hire -> puesto, Model, sales lead
    del pipeline, fechas, budget/salario/fees, grabaciones) + los to-dos del stage + el
    mail de Credit Loop. Si la cuenta ya tiene oportunidades sin negocio atado, **no crea**:
    el negocio queda «esperando decisión» con las candidatas y una persona elige
    **Vincular** o **Es nueva, creala** (mismo freno que el panel de Opportunities).
  * Etapas siguientes -> empuja la oportunidad **sólo hacia adelante** con
    `decide_stage_transition()` (NDA Sent -> NDA Sent, NDA Signed -> Sourcing). Candidate
    Signed / Closed Won / Closed Lost los decide la oportunidad (la recruiter): esos
    stages tienen efectos (hire activo, créditos, cliente inactivo, push a HubSpot) que
    viven en `update_opportunity_stage`. `deals.reflect()` trae ese avance al negocio.

**Anti doble creación durante la transición**: un negocio que vino de HubSpot
(`hubspot_deal_id`) NO crea nada desde acá — eso lo sigue haciendo el sync de
oportunidades de siempre, y `deals.reflect()` lo ata por `hubspot_deal_id`. El día que
dejen HubSpot se prende `HUB_IS_SOURCE` (y se apagan los dos crons de HubSpot).

Las oportunidades que crea esto nacen con `hubspot_deal_id` NULL: para el sync de HubSpot
son «cargadas a mano» y no las toca nunca. Un negocio dummy no crea nada.
"""
from __future__ import annotations

import logging

from psycopg2.extras import Json

from prospecting import deals as D
from prospecting.deal_fields import CLOSED_LOST

# El día del corte (sin HubSpot), True: también los negocios importados de HubSpot crean
# cuenta / oportunidad desde el Hub.
HUB_IS_SOURCE = False

# Campo del negocio -> columna de `opportunity` (se completan sólo si están vacías).
BUSINESS_TO_OPP = {
    "min_budget": "min_budget", "max_budget": "max_budget",
    "min_salary": "min_salary", "max_salary": "max_salary",
    "years_experience": "years_experience",
    "expected_fee": "expected_fee", "expected_revenue": "expected_revenue",
    "expected_setup_fee": "fee",
}
RECORDING_TO_OPP = {"intro_call_recording": "first_meeting_recording", "deep_dive_recording": "deepdive_recording"}
PUSHABLE = {"deep_dive": "Deep Dive", "nda_sent": "NDA Sent", "nda_signed": "Sourcing"}


def _hs():
    # Import tardío: routes/hubspot_routes.py es un módulo de Flask pesado.
    from routes import hubspot_routes as hs
    return hs


def applies(deal: dict) -> tuple[bool, str | None]:
    if deal.get("is_dummy"):
        return False, "Negocio de prueba: no crea cuenta ni oportunidad."
    if deal.get("hubspot_deal_id") and not HUB_IS_SOURCE:
        return False, "Viene de HubSpot: la cuenta y la oportunidad las sigue creando el sync de HubSpot."
    return True, None


# --------------------------------------------------------------------------- #
def _context(cur, deal: dict) -> tuple[dict | None, dict | None]:
    company = None
    if deal.get("company_id"):
        cur.execute("SELECT * FROM prospect_companies WHERE id = %s", (deal["company_id"],))
        company = cur.fetchone()
    cur.execute(
        """
        SELECT ct.* FROM prospect_deal_contacts dc JOIN prospect_contacts ct ON ct.id = dc.contact_id
         WHERE dc.deal_id = %s ORDER BY dc.created_at LIMIT 1
        """,
        (deal["id"],),
    )
    contact = cur.fetchone()
    if contact is None and company is not None:
        cur.execute("SELECT * FROM prospect_contacts WHERE company_id = %s ORDER BY is_primary DESC, created_at LIMIT 1",
                    (company["id"],))
        contact = cur.fetchone()
    return (dict(company) if company else None), (dict(contact) if contact else None)


def account_payload(cur, deal: dict) -> dict:
    from utils.hubspot_opportunities import PIPELINE_SALES_LEAD

    company, contact = _context(cur, deal)
    company, contact = company or {}, contact or {}
    cprops = contact.get("props") or {}

    def first(*vals):
        return next((v for v in vals if v not in (None, "", [])), None)

    # Lo que pide el popup de SQL (copias «(Deal)», 2026-11-04) manda: es lo mismo que el sync
    # de HubSpot lee del deal para armar la cuenta. Si falta, la empresa / el contacto.
    return {
        "name": first(deal.get("company_name_deal"), company.get("name"), deal.get("name")),
        "website": first(deal.get("website"), company.get("website")),
        "linkedin": first(deal.get("linkedin_company"), company.get("linkedin_url")),
        "size": first(deal.get("headcount"), company.get("size")),
        "state": first(deal.get("state_region"), company.get("state")),
        "about": company.get("description"),
        "industry": first(deal.get("industry"), cprops.get("industria")),
        "pain_points": deal.get("pain_point"),
        "outsource": deal.get("outsourced_before"),
        "position": first(deal.get("position"), cprops.get("position")),
        "type": deal.get("company_type"),
        "contract": deal.get("model"),
        "conversion_channel": first(deal.get("conversion_channel"), cprops.get("conversion_channel")),
        "lead_source_detail": first(deal.get("origin_detail"), cprops.get("origin_detail")),
        "mail": contact.get("email"),
        "contact_name": contact.get("first_name"),
        "contact_surname": contact.get("last_name"),
        "where_come_from": first(deal.get("origin"), cprops.get("origin"), company.get("lead_source")),
        "account_manager": PIPELINE_SALES_LEAD.get(deal["pipeline_key"]),
        "hubspot_company_id": company.get("hubspot_company_id"),
        "hubspot_contact_id": contact.get("hubspot_contact_id"),
        "vintti_ai": deal["pipeline_key"] == "vintti_ai",
    }


def _ensure_account(cur, deal: dict, actor, report: dict) -> int | None:
    hs = _hs()
    if deal.get("account_id"):
        return deal["account_id"]
    payload = account_payload(cur, deal)
    existing = hs._preview_existing_account(cur, payload)
    if existing:
        account_id = existing["account_id"]
        hs._link_existing_account_to_hubspot(cur, account_id, payload)
        report["account"] = {"id": account_id, "action": "vinculada", "name": existing.get("client_name")}
    else:
        res = hs._insert_or_update_account(cur, payload)
        account_id = res["account_id"]
        report["account"] = {"id": account_id, "action": "creada" if res["action"] == "created" else "vinculada",
                             "name": payload.get("name")}
    hs._marcar_cuenta_vintti_ai(cur, account_id, deal["pipeline_key"], False)
    cur.execute("UPDATE prospect_deals SET account_id = %s WHERE id = %s", (account_id, deal["id"]))
    D._log_hub(cur, deal, actor, f"account:{account_id}")
    deal["account_id"] = account_id
    return account_id


def _write_sql_date(cur, deal: dict, account_id: int, actor, report: dict) -> None:
    from dashboards.datasets._now import today_ar

    sql_date = deal.get("sql_date") or today_ar().isoformat()
    cur.execute("UPDATE account SET sql_date = %s WHERE account_id = %s AND sql_date IS NULL", (sql_date, account_id))
    if cur.rowcount:
        report["sql_date"] = sql_date
    if not deal.get("sql_date"):
        D.update_deal(cur, deal["id"], {"sql_date": sql_date}, actor, source="hub")
        deal["sql_date"] = sql_date


def _candidates(cur, deal: dict, account_id: int) -> list[dict]:
    from dashboards.datasets._now import today_ar

    cands = _hs()._link_candidates(cur, account_id, deal.get("role_to_hire") or "",
                                   deal_deep_dive_date=today_ar())
    if not cands:
        return []
    cur.execute("SELECT opportunity_id FROM prospect_deals WHERE opportunity_id = ANY(%s) AND id <> %s",
                ([c["opportunity_id"] for c in cands], deal["id"]))
    taken = {r["opportunity_id"] for r in cur.fetchall()}
    return [c for c in cands if c["opportunity_id"] not in taken]


def _fill_opp_fields(cur, opp_id: int, deal: dict) -> dict:
    """Completa en la oportunidad budget/salario/fees/grabaciones que estén vacíos. Nunca
    pisa: esos números se renegocian dentro del hub (mismo criterio que el sync)."""
    done = {}
    nums = {col: deal.get(k) for k, col in BUSINESS_TO_OPP.items() if deal.get(k) not in (None, "")}
    if nums:
        cur.execute(
            f"SELECT {', '.join(nums)} FROM opportunity WHERE opportunity_id = %s", (opp_id,)
        )
        cur_vals = cur.fetchone() or {}
        nums = {c: v for c, v in nums.items() if cur_vals.get(c) is None}
        if nums:
            cur.execute(
                f"UPDATE opportunity SET {', '.join(f'{c} = COALESCE({c}, %s)' for c in nums)} WHERE opportunity_id = %s",
                list(nums.values()) + [opp_id],
            )
            done.update(nums)
    recs = {col: deal.get(k) for k, col in RECORDING_TO_OPP.items() if str(deal.get(k) or "").strip()}
    if recs:
        cur.execute(f"SELECT {', '.join(recs)} FROM opportunity WHERE opportunity_id = %s", (opp_id,))
        cur_vals = cur.fetchone() or {}
        recs = {c: v for c, v in recs.items() if not str(cur_vals.get(c) or "").strip()}
        if recs:
            cur.execute(
                f"UPDATE opportunity SET {', '.join(f'{c} = COALESCE(NULLIF({c}, %s), %s)' for c in recs)} "
                "WHERE opportunity_id = %s",
                [x for v in recs.values() for x in ("", v)] + [opp_id],
            )
            done.update(recs)
    return done


def _stage_dates(deal: dict, stage_key: str) -> dict:
    from dashboards.datasets._now import today_ar

    today = today_ar().isoformat()
    r = D.rank(stage_key) or 0
    return {
        "deep_dive_date": today if r >= D.rank("deep_dive") else None,
        "nda_sent_date": deal.get("nda_sent_date") or (today if r >= D.rank("nda_sent") else None),
        "nda_signature_or_start_date": deal.get("nda_signed_date") or (today if r >= D.rank("nda_signed") else None),
    }


def _create_opportunity(cur, deal: dict, account_id: int, actor, report: dict) -> int | None:
    from utils import hubspot_opportunities as hs_opps
    from utils.credit_loop import maybe_send_credit_available_email_for_new_opportunity
    from utils.hr_lead_todo import create_stage_todos

    hs = _hs()
    dates = _stage_dates(deal, deal["stage_key"])
    stage = hs_opps.initial_stage_for_new_opportunity(deal["stage_key"], dates) or "Deep Dive"
    new_id = hs._insert_opportunity_from_deal(cur, {
        "account_id": account_id,
        "opp_model": deal.get("model"),
        "position": deal.get("role_to_hire"),
        "sales_lead": hs_opps.PIPELINE_SALES_LEAD.get(deal["pipeline_key"]),
        "opp_stage": stage,
        "deep_dive_date": dates["deep_dive_date"],
        "nda_sent_date": dates["nda_sent_date"],
        "nda_signed_date": dates["nda_signature_or_start_date"],
        "deal_id": None, "pipeline_id": None, "dealstage_id": None,
    })
    # No es un deal de HubSpot: sin foto del Model (si un día se ata a uno, cuenta como primera vez).
    cur.execute("UPDATE opportunity SET hubspot_model_seen = NULL, hubspot_synced_at = NULL WHERE opportunity_id = %s",
                (new_id,))
    cur.execute(
        "UPDATE prospect_deals SET opportunity_id = %s, hub_status = NULL, hub_note = NULL WHERE id = %s",
        (new_id, deal["id"]),
    )
    D._log_hub(cur, deal, actor, f"opportunity:{new_id}")
    deal["opportunity_id"] = new_id
    filled = _fill_opp_fields(cur, new_id, deal)
    report["opportunity"] = {"id": new_id, "action": "creada", "stage": stage, "campos": sorted(filled)}
    try:
        cur.execute("SAVEPOINT deal_todos")
        create_stage_todos(cur, new_id, stage)
        cur.execute("RELEASE SAVEPOINT deal_todos")
    except Exception:  # noqa: BLE001
        cur.execute("ROLLBACK TO SAVEPOINT deal_todos")
        logging.exception("create_stage_todos falló para la opp %s (negocio %s)", new_id, deal["id"])
    try:
        cur.execute("SAVEPOINT deal_credit")
        cur.execute("SELECT client_name FROM account WHERE account_id = %s", (account_id,))
        a = cur.fetchone() or {}
        report["credit_loop_notice"] = maybe_send_credit_available_email_for_new_opportunity(
            cur, account_id=account_id, opportunity_id=new_id, opp_model=deal.get("model"),
            opp_position_name=deal.get("role_to_hire"), client_name=a.get("client_name"),
        )
        cur.execute("RELEASE SAVEPOINT deal_credit")
    except Exception as exc:  # noqa: BLE001
        cur.execute("ROLLBACK TO SAVEPOINT deal_credit")
        logging.exception("credit loop email falló para la opp %s", new_id)
        report["credit_loop_notice"] = {"sent": False, "error": str(exc)[:200]}
    if stage.lower() == "sourcing":
        report.setdefault("after_commit", []).append(("sourcing", new_id, None))
    return new_id


def _advance_opportunity(cur, deal: dict, actor, report: dict) -> None:
    """La oportunidad ya existe: el negocio la empuja sólo hacia adelante."""
    from utils import hubspot_opportunities as hs_opps
    from utils.hr_lead_todo import create_stage_todos

    target = PUSHABLE.get(deal["stage_key"])
    opp_id = deal["opportunity_id"]
    cur.execute("SELECT opp_stage FROM opportunity WHERE opportunity_id = %s", (opp_id,))
    o = cur.fetchone()
    if o is None:
        return
    filled = _fill_opp_fields(cur, opp_id, deal)
    if not target:
        if deal["stage_key"] in ("signed", "closed_won", CLOSED_LOST) and \
                (o["opp_stage"] or "").strip().lower() not in ("signed", "close win", "closed lost", "stop"):
            report["opportunity"] = {"id": opp_id, "action": "sin_cambios", "stage": o["opp_stage"],
                                     "aviso": "Ese stage se mueve desde Opportunities (tiene efectos en el hire, "
                                              "créditos y la cuenta)."}
        if filled:
            report.setdefault("opportunity", {"id": opp_id, "stage": o["opp_stage"]})["campos"] = sorted(filled)
        return
    new_stage, why = hs_opps.decide_stage_transition(o["opp_stage"], target)
    if not new_stage:
        report["opportunity"] = {"id": opp_id, "action": "sin_cambios", "stage": o["opp_stage"], "motivo": why,
                                 "campos": sorted(filled)}
        return
    dates = _stage_dates(deal, deal["stage_key"])
    cur.execute(
        """
        UPDATE opportunity SET opp_stage = %s,
               deep_dive_date = COALESCE(deep_dive_date, %s),
               nda_sent_date = COALESCE(nda_sent_date, %s),
               nda_signature_or_start_date = COALESCE(nda_signature_or_start_date, %s)
         WHERE opportunity_id = %s
        """,
        (new_stage, dates["deep_dive_date"], dates["nda_sent_date"] if D.rank(deal["stage_key"]) >= D.rank("nda_sent") else None,
         dates["nda_signature_or_start_date"] if new_stage == "Sourcing" else None, opp_id),
    )
    try:
        cur.execute("SAVEPOINT deal_todos")
        create_stage_todos(cur, opp_id, new_stage)
        cur.execute("RELEASE SAVEPOINT deal_todos")
    except Exception:  # noqa: BLE001
        cur.execute("ROLLBACK TO SAVEPOINT deal_todos")
        logging.exception("create_stage_todos falló para la opp %s", opp_id)
    report["opportunity"] = {"id": opp_id, "action": "movida", "from": o["opp_stage"], "stage": new_stage,
                             "campos": sorted(filled)}
    if new_stage == "Sourcing":
        report.setdefault("after_commit", []).append(("sourcing", opp_id, o["opp_stage"]))


def run(cur, deal_id: int, actor: str | None) -> dict:
    """Aplica la regla al negocio en su etapa actual. Idempotente: se puede llamar después
    de cualquier cambio (etapa, campos, contactos). Devuelve un reporte para la página."""
    deal = D.get_deal(cur, deal_id)
    if deal is None:
        return {}
    ok, why = applies(deal)
    report: dict = {}
    if not ok:
        report["skip"] = why
        return report
    r = D.rank(deal["stage_key"])
    if deal.get("opportunity_id"):
        _advance_opportunity(cur, deal, actor, report)
        return report
    if r is None or r < D.rank("sql"):
        return report
    account_id = _ensure_account(cur, deal, actor, report)
    if account_id:
        _write_sql_date(cur, deal, account_id, actor, report)
    if r < D.rank("deep_dive") or not account_id:
        return report
    if not str(deal.get("role_to_hire") or "").strip():
        report["aviso"] = "Falta Role to hire: sin eso no se crea la oportunidad."
        return report
    if not deal.get("hub_mark_new"):
        cands = _candidates(cur, deal, account_id)
        if cands:
            cur.execute("UPDATE prospect_deals SET hub_status = 'waiting', hub_note = %s WHERE id = %s",
                        (Json({"candidates": [c["opportunity_id"] for c in cands]}), deal["id"]))
            report["waiting"] = cands
            return report
    _create_opportunity(cur, deal, account_id, actor, report)
    return report


def link_opportunity(cur, deal_id: int, opportunity_id: int, actor: str | None) -> dict:
    deal = D.get_deal(cur, deal_id)
    if deal is None:
        raise LookupError("deal")
    cur.execute("SELECT opportunity_id, account_id, hubspot_deal_id FROM opportunity WHERE opportunity_id = %s",
                (opportunity_id,))
    o = cur.fetchone()
    if o is None:
        raise LookupError("opportunity")
    if (o["hubspot_deal_id"] or "").strip() and o["hubspot_deal_id"] != deal.get("hubspot_deal_id"):
        raise ValueError("Esa oportunidad ya está atada a otro deal de HubSpot.")
    cur.execute("SELECT id FROM prospect_deals WHERE opportunity_id = %s AND id <> %s", (opportunity_id, deal_id))
    if cur.fetchone():
        raise ValueError("Esa oportunidad ya está atada a otro negocio.")
    cur.execute(
        "UPDATE prospect_deals SET opportunity_id = %s, account_id = COALESCE(account_id, %s), hub_status = NULL, "
        "hub_note = NULL WHERE id = %s",
        (opportunity_id, o["account_id"], deal_id),
    )
    D._log_hub(cur, deal, actor, f"opportunity_linked:{opportunity_id}")
    return run(cur, deal_id, actor)


def unlink_opportunity(cur, deal_id: int, actor: str | None) -> None:
    deal = D.get_deal(cur, deal_id)
    if deal is None:
        raise LookupError("deal")
    if not deal.get("opportunity_id"):
        return
    cur.execute("UPDATE prospect_deals SET opportunity_id = NULL WHERE id = %s", (deal_id,))
    D._log_hub(cur, deal, actor, f"opportunity_unlinked:{deal['opportunity_id']}")


def mark_new(cur, deal_id: int, actor: str | None) -> dict:
    cur.execute("UPDATE prospect_deals SET hub_mark_new = TRUE, hub_status = NULL, hub_note = NULL WHERE id = %s "
                "RETURNING id", (deal_id,))
    if cur.fetchone() is None:
        raise LookupError("deal")
    return run(cur, deal_id, actor)


def waiting_candidates(cur, deal: dict) -> list[dict]:
    """Candidatas en vivo (no la foto guardada), como el panel de Opportunities."""
    if deal.get("hub_status") != "waiting" or not deal.get("account_id"):
        return []
    return _candidates(cur, deal, deal["account_id"])


def after_commit(report: dict) -> None:
    """Lo que va después del commit (Slack de Sourcing), nunca levanta."""
    for kind, opp_id, prev in report.pop("after_commit", []) or []:
        if kind == "sourcing":
            try:
                from utils.sourcing_slack import notify_first_sourcing_async
                notify_first_sourcing_async(opp_id, prev)
            except Exception:  # noqa: BLE001
                logging.exception("sourcing slack falló para la opp %s", opp_id)
