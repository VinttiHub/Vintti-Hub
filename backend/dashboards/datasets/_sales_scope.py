"""Sales-tab scope = los AEs Mariano + Bahía (M+B).

Fuente única de verdad para "quién es M+B" en los datasets de la pestaña Sales.
Antes esta lista + helper estaban DUPLICADOS idénticos en 9 archivos (R3 del audit);
ahora viven acá y se importan. Cambiar la definición de M+B = editar solo este archivo.

Override por entorno: `DASHBOARD_SALES_AES` = lista de emails separada por comas
(p.ej. "mariano@vintti.com,bahia@vintti.com"). Si está vacía, usa el default.

OJO con el scope por etapa (ver memoria project-sales-tab-filter):
  - Funnel temprano (SQL, account creado, Deep Dive, NDA) → filtrar
    `account.account_manager` ∈ M+B.
  - Métricas de deals GANADOS (Close Win, win rate) → filtrar
    `opportunity.opp_sales_lead` ∈ M+B, porque al ganar el deal el
    `account_manager` se reasigna al AM post-venta (Lara) y filtrar por
    account_manager borraría todas las wins.
Este módulo solo provee la LISTA M+B; cada dataset elige la columna correcta.
"""
from __future__ import annotations

import os

SALES_LEADS_DEFAULT = ("mariano@vintti.com", "bahia@vintti.com")


def sales_leads() -> list[str]:
    """Lista de emails (lowercase) del scope Sales = M+B, override por env."""
    raw = os.environ.get("DASHBOARD_SALES_AES", "")
    parts = [p.strip().lower() for p in raw.split(",") if p.strip()]
    return parts or list(SALES_LEADS_DEFAULT)
