-- REVIERTE `20260921_opp_sales_lead_lara_to_pilar.sql`.
--
-- La owner decidio el 2026-09-22 que las opps que llevaba Lara **siguen siendo de
-- Lara**: `opp_sales_lead` dice quien VENDIO el deal, y eso no se traspasa con el rol.
-- Lo unico que se traspasa es el book (`account.account_manager`), que ya esta en Pilar.
--
-- La continuidad de las cards del tab AM NO depende de este campo: la dan
-- `utils/am_roster.am_history()` (AM de hoy + `PAST_AMS`, o sea Pilar + Lara) y los
-- datasets que la usan — `lara_winrate_*`, `new_opps_am_*`, `nrr_*_detail`,
-- `active_pipeline`, `op_one_shot_kill_*`. Verificado: los numeros del dashboard son
-- los mismos con las opps en Lara o en Pilar.
--
-- Por eso `PAST_AMS` queda como linea load-bearing: si se saca a Lara de ahi, las cards
-- del tab AM se vacian (Pilar tiene 0 opps a su nombre).
--
-- Alcance: solo las filas que este backup movio y que hoy siguen en Pilar. Si alguien
-- cambio una a mano en el medio, no se toca.

BEGIN;

UPDATE opportunity o
SET opp_sales_lead = b.opp_sales_lead_prev
FROM opp_sales_lead_backup_20260921 b
WHERE b.opportunity_id = o.opportunity_id
  AND LOWER(TRIM(COALESCE(o.opp_sales_lead, ''))) = 'pilar@vintti.com'
  AND NULLIF(TRIM(b.opp_sales_lead_prev), '') IS NOT NULL;

COMMIT;

-- El backup se deja: documenta que se corrio y permite auditar el ida y vuelta.
