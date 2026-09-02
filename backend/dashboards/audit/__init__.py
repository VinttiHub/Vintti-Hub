"""Auditoria automatica de las metricas del dashboard.

Recalcula cada numero que el dashboard muestra y verifica invariantes que hoy
solo se comprueban mirando la pantalla: que el detalle de un drawer cuadre con
su card, que un porcentaje sea posible, que una columna renombrada no haya
dejado una card en blanco.

Uso:
    python -m dashboards.audit                # todo, sin escribir nada
    python -m dashboards.audit --tab sales    # una sola pestana
"""
from .runner import run  # noqa: F401
