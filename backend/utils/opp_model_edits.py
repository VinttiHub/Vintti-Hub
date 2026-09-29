"""Marca de "el Model de esta opp lo corrigio una persona en el hub".

El sync HubSpot -> hub (`_apply_model_from_hubspot()` en routes/hubspot_routes.py)
copia el Model de HubSpot la PRIMERA vez que ve un deal atado (foto
`hubspot_model_seen` en NULL): una opp creada a mano desde el modal arranca en
Staffing por default y ese valor no es una decision de nadie (PGAM #838).

Pero si la recruiter ya habia corregido el Model en el hub, esa primera vez la
pisaba igual. Paso con founderfirst (825) y Summit Chase (808) el 2026-09-24: el
deal decia Staffing, la recruiter las habia puesto en Recruiting, y al moverse el
deal de stage en HubSpot el sync las devolvio a Staffing.

`opportunity.opp_model_edited_at` se sella cuando `PATCH /opportunities/<id>/fields`
cambia `opp_model`. Con el sello puesto, la primera vez del sync solo saca la foto.

La columna se crea aca y no en `_ensure_hubspot_opportunity_columns()`, por el mismo
cortocircuito que obligo a separar `hubspot_pushed_at` y `hubspot_model_seen`.
"""
from __future__ import annotations

import logging

_EDITED_AT_READY = False


def ensure_model_edited_column(cursor):
    global _EDITED_AT_READY
    if _EDITED_AT_READY:
        return
    cursor.execute(
        """
        SELECT 1 FROM information_schema.columns
         WHERE table_name = 'opportunity' AND column_name = 'opp_model_edited_at'
        """
    )
    if cursor.fetchone() is None:
        cursor.execute(
            "ALTER TABLE opportunity ADD COLUMN IF NOT EXISTS opp_model_edited_at TIMESTAMPTZ"
        )
    _EDITED_AT_READY = True


def mark_model_edited(cursor, opportunity_id, previous_model, new_model):
    """Sella la edicion manual si el Model cambio de verdad. Nunca levanta.

    Corre dentro de la transaccion del PATCH, asi que va con SAVEPOINT: un error aca
    abortaria la transaccion y el COMMIT final desharia tambien el cambio de Model
    que la persona acaba de hacer.
    """
    prev = (previous_model or "").strip().lower()
    new = (new_model or "").strip().lower()
    if not new or prev == new:
        return
    cursor.execute("SAVEPOINT opp_model_edited")
    try:
        ensure_model_edited_column(cursor)
        cursor.execute(
            "UPDATE opportunity SET opp_model_edited_at = NOW() WHERE opportunity_id = %s",
            (opportunity_id,),
        )
        cursor.execute("RELEASE SAVEPOINT opp_model_edited")
    except Exception:
        cursor.execute("ROLLBACK TO SAVEPOINT opp_model_edited")
        logging.exception("No se pudo sellar opp_model_edited_at (opp=%s)", opportunity_id)


def model_edited_at(cursor, opportunity_id):
    """Cuando se corrigio el Model a mano en el hub, o None.

    Solo lee: si la columna todavia no existe (nadie edito un Model desde el deploy)
    devuelve None sin crearla, para que un dry run del sync no toque el esquema.
    """
    if not _EDITED_AT_READY:
        cursor.execute(
            """
            SELECT 1 FROM information_schema.columns
             WHERE table_name = 'opportunity' AND column_name = 'opp_model_edited_at'
            """
        )
        if cursor.fetchone() is None:
            return None
    cursor.execute(
        "SELECT opp_model_edited_at FROM opportunity WHERE opportunity_id = %s",
        (opportunity_id,),
    )
    row = cursor.fetchone()
    if not row:
        return None
    return row["opp_model_edited_at"] if isinstance(row, dict) else row[0]
