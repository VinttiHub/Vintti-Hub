"""Hoy en hora Argentina (UTC-3, sin DST desde 2009).

Reemplazo de `datetime.utcnow().date()` como default de 'corte'/'hoy' en los
helpers de período. Con UTC, entre las 21:00 y 23:59 de Argentina (00:00–02:59
UTC) el "hoy" saltaba prematuramente al día siguiente, corriendo la ventana
default. ARG es UTC-3 fijo todo el año, así que un offset de -3h es exacto.

R11 sub-A: aplicado a los helpers compartidos `_periods.window_bounds` y
`_period.monthly_range` (que rutean la mayoría de los datasets). Los datasets que
todavía usan `datetime.utcnow().date()` inline quedan con el rollover marginal
(decisión del owner: no barrer los ~150 por impacto bajo).
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone


def today_ar() -> date:
    """Fecha de hoy en Argentina (UTC-3)."""
    return (datetime.now(timezone.utc) - timedelta(hours=3)).date()
