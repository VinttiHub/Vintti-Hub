-- ####################################################################
-- ##  YA REVERTIDO. NO VOLVER A CORRER.                             ##
-- ##  Se corrio el 2026-09-21 y se deshizo el 2026-09-22 con        ##
-- ##  `20260922_opp_sales_lead_revert_to_lara.sql`: la owner        ##
-- ##  decidio que las opps que vendio Lara siguen siendo de Lara.   ##
-- ##  Se deja el archivo para que quede registro de lo que corrio.  ##
-- ####################################################################
--
-- Segunda parte del traspaso del rol AM: `opportunity.opp_sales_lead` Lara -> Pilar.
--
-- Contexto (2026-09-21): la owner pidio que el traspaso sea completo, no solo el book.
-- Yo habia recomendado NO tocar este campo (dice quien VENDIO el deal, y venderlo lo
-- vendio Lara) y resolver la continuidad por codigo con `am_history()`. La owner
-- reafirmo que queria el reemplazo literal, se corrio, y al dia siguiente decidio
-- volverlo atras. Conclusion que queda: el rol se traspasa, la autoria de la venta no.
--
-- Alcance medido antes de correrlo: 287 opps (174 Close Win, 97 Closed Lost,
-- 11 Interviewing, 4 Sourcing, 1 Signed). `opp_hr_lead` NO se toca: es el recruiter,
-- y Lara no figura en ninguna (0 filas), mientras Pilar ya tiene 177 por su trabajo
-- anterior de recruiter.
--
-- Que cambiaba de verdad (el dashboard NO, porque `am_history()` ya cubria a las dos —
-- medido: Conversion Rate AM, New opps AM y GMRR del AM dieron identico antes y
-- despues, y tambien despues de revertir):
--   * recordatorios (`reminders_routes`), alerta de cliente inactivo y digest de Slack
--     pasaban a pingear a Pilar en vez de a Lara;
--   * el gate de CV Review (el sales lead aprueba el CV) pasaba a Pilar. Los reviews ya
--     hechos no se movian: comparan contra el snapshot que guardaron, no contra
--     `opportunity.opp_sales_lead` de hoy (cv_review_routes.py:2088);
--   * `/accounts/<id>/sales-lead/suggest` (mayoria por opp) pasaba a sugerir Pilar.
--   * Comisiones AE: sin efecto, su scope es Mariano + Bahia.

BEGIN;

CREATE TABLE IF NOT EXISTS opp_sales_lead_backup_20260921 (
  opportunity_id       integer PRIMARY KEY,
  opp_sales_lead_prev  text,
  moved_at             timestamptz NOT NULL DEFAULT now()
);

INSERT INTO opp_sales_lead_backup_20260921 (opportunity_id, opp_sales_lead_prev)
SELECT o.opportunity_id, o.opp_sales_lead
FROM opportunity o
WHERE LOWER(TRIM(COALESCE(o.opp_sales_lead, ''))) = 'lara@vintti.com'
ON CONFLICT (opportunity_id) DO NOTHING;

UPDATE opportunity o
SET opp_sales_lead = 'pilar@vintti.com'
WHERE LOWER(TRIM(COALESCE(o.opp_sales_lead, ''))) = 'lara@vintti.com';

COMMIT;

-- Para revertir (es lo que se corrio el 2026-09-22):
--   UPDATE opportunity o SET opp_sales_lead = b.opp_sales_lead_prev
--   FROM opp_sales_lead_backup_20260921 b WHERE b.opportunity_id = o.opportunity_id;
