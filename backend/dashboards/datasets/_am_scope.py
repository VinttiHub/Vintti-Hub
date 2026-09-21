"""Quien es Account Manager, para los datasets del dashboard.

La implementacion vive en `utils/am_roster.py`, que es neutro y lo comparten los
datasets y el PATCH de `account`. Aca solo se le ponen los dos nombres con los que lo
piden los datasets, porque son dos preguntas distintas y confundirlas rompe cosas
opuestas:

  - `am_leads()`   : quien es AM HOY. Va contra `account.account_manager`, que guarda al
                     dueno ACTUAL de la cuenta y se reasigna solo al ganarla.

  - `am_history()` : quien ha sido AM alguna vez. Va contra `opportunity.opp_sales_lead`
                     y `opp_hr_lead`. Si aca fuera solo el AM de hoy, las cards del tab
                     AM se vaciarian de golpe cada vez que cambia el organigrama.
"""
from __future__ import annotations

from utils.am_roster import PAST_AMS, am_history, current_ams

am_leads = current_ams

__all__ = ["am_leads", "am_history", "PAST_AMS"]
