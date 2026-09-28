"""Texto de la ventana de una métrica rolling: "01-jul → 28-sep".

Las cards de churn M3 decían "30d" o "Last 90d" y no se veía desde qué fecha cuenta
la cohorte: con corte 28-sep la de 90 días arranca el 01-jul, y quien arrancó el
30-jun queda afuera (pasó con Jesus Salcido, 2026-09-28). Mismo formato corto que la
base del NRR (`base_label_sql`), para que el dashboard hable un solo idioma de fechas.
"""
from __future__ import annotations

from ._nrr_decomp import base_label_sql


def window_label_sql(ini_expr: str, fin_expr: str) -> str:
    return f"({base_label_sql(ini_expr)} || ' → ' || {base_label_sql(fin_expr)})"
