"""Helpers del mail de sign off (rechazo) a candidatos del pipeline.

La columna `opportunity_candidates.signoff_email_sent_at` la crea
`backend/sql/20260902_add_signoff_email_sent_at.sql`, pero también se
auto-crea desde el endpoint de envío para no depender de que alguien
corra la migración a mano.

Ojo: el ADD COLUMN toma ACCESS EXCLUSIVE sobre la tabla, así que se hace
SÓLO desde el endpoint de envío (acción puntual del usuario) y nunca desde
una ruta de lectura — ver la nota de `backend/db.py` sobre `users.color`.
Las lecturas usan `signoff_sent_column_exists()`, que sólo consulta el
catálogo (barato) y cachea el resultado cuando la columna ya está.
"""
from __future__ import annotations

# Sólo se cachea el True: si la columna todavía no existe hay que volver a
# mirar, porque otro worker (o la migración a mano) puede haberla creado y este
# proceso se quedaría con un False pegado hasta el próximo restart.
_HAS_SIGNOFF_SENT_COLUMN = False


def signoff_sent_column_exists(cur) -> bool:
    """True si `opportunity_candidates.signoff_email_sent_at` ya existe."""
    global _HAS_SIGNOFF_SENT_COLUMN
    if _HAS_SIGNOFF_SENT_COLUMN:
        return True
    cur.execute(
        """
        SELECT 1
          FROM information_schema.columns
         WHERE table_name = 'opportunity_candidates'
           AND column_name = 'signoff_email_sent_at'
         LIMIT 1
        """
    )
    _HAS_SIGNOFF_SENT_COLUMN = cur.fetchone() is not None
    return _HAS_SIGNOFF_SENT_COLUMN


def ensure_signoff_sent_column(cur) -> None:
    """Crea la columna si falta. Sólo desde el endpoint de envío."""
    global _HAS_SIGNOFF_SENT_COLUMN
    if _HAS_SIGNOFF_SENT_COLUMN:
        return
    cur.execute(
        "ALTER TABLE opportunity_candidates "
        "ADD COLUMN IF NOT EXISTS signoff_email_sent_at TIMESTAMPTZ"
    )
    _HAS_SIGNOFF_SENT_COLUMN = True


def first_name(full_name: str | None) -> str:
    """Primer nombre del candidato para el saludo. Fallback: 'there'."""
    parts = (full_name or "").strip().split()
    return parts[0] if parts else "there"


def personalize_signoff_body(body: str, full_name: str | None) -> str:
    """Reemplaza el placeholder XXX del template por el nombre del candidato."""
    return (body or "").replace("XXX", first_name(full_name))
