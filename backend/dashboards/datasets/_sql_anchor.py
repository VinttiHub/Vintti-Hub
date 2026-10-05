"""Cuándo una cuenta se volvió SQL: el ancla de las cards de SQL del tab Sales.

Hasta el 2026-10-05 el SQL se anclaba en `account.sql_meeting_date` (el Meeting
Date & Time del contacto en HubSpot, que escribe el sync de SQL contacts). Desde
ese día HubSpot tiene un stage "SQL" en los dos pipelines de deals, y el sync de
opportunities sella `account.sql_date` con la "SQL Date (Deal)" (o la entrada al
stage). Pedido de la owner: usar la SQL Date **sólo para los que se califiquen de
hoy en adelante**, así no cambia ningún número histórico.

    1. sql_meeting_date anterior al corte  -> sql_meeting_date (historia congelada)
    2. sql_date desde el corte             -> sql_date
    3. si no                               -> sql_meeting_date

La rama 1 va primero a propósito: una cuenta que ya era SQL antes del corte y
vuelve a pasar por el stage no cambia de mes en ninguna card. El sync tampoco
escribe nunca una `sql_date` anterior al corte (`sql_date_from_deal` en
utils/hubspot_opportunities.py, mismo `SQL_DATE_CUTOVER`): si tocás uno, tocá el otro.

Sin `%` en el SQL: psycopg2 lo leería como placeholder.
El tab Marketing NO usa esto: sigue leyendo Meeting Date & Time en vivo de los
contactos (decisión de la owner, 2026-10-05).
"""
from __future__ import annotations

SQL_CUTOVER = "2026-10-05"


def sql_anchor(alias: str = "a") -> str:
    return (
        f"(CASE WHEN {alias}.sql_meeting_date < DATE '{SQL_CUTOVER}' THEN {alias}.sql_meeting_date"
        f" WHEN {alias}.sql_date >= DATE '{SQL_CUTOVER}' THEN {alias}.sql_date"
        f" ELSE {alias}.sql_meeting_date END)"
    )


SQL_ANCHOR = sql_anchor("a")
