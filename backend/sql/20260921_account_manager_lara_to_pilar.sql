-- Traspaso del rol Account Manager: Lara Reinhardt -> Pilar Flores Levalle.
-- ESTADO: aplicado el 2026-09-21 y VIGENTE. El book es de Pilar.
--
-- Contexto: cambio de organigrama. Lara pasa a Chief of Staff y Pilar queda como unica
-- AM (`users.role = 'AM'`). `account.account_manager` guarda al dueno ACTUAL de la
-- cuenta y no tiene historia, asi que reasignarlo recalcula tambien las cards
-- historicas del dashboard — decision explicita de la owner.
--
-- Este script toca SOLO `account.account_manager`. El traspaso de
-- `opportunity.opp_sales_lead` se intento aparte y se REVIRTIO el 2026-09-22: ese campo
-- dice quien VENDIO el deal y no se traspasa con el rol (ver
-- `20260922_opp_sales_lead_revert_to_lara.sql`). Las 287 opps siguen siendo de Lara.
--
-- OJO, esto solo no alcanza: el `crm.js` DEPLOYADO reasigna toda cuenta Active Client
-- al AM que tiene escrito a mano, asi que a las horas de correr esto 80 de las 123
-- cuentas habian vuelto a Lara. El freno que lo sostiene es del lado del servidor:
-- `utils/am_roster.normalize_account_manager()`, enganchado en el PATCH de
-- `accounts_routes.py`. Correr este script sin ese freno deployado no sirve de nada.
--
-- Reversible: el backup guarda el valor anterior de cada fila tocada.

BEGIN;

CREATE TABLE IF NOT EXISTS account_manager_backup_20260921 (
  account_id            integer PRIMARY KEY,
  account_manager_prev  text,
  moved_at              timestamptz NOT NULL DEFAULT now()
);

INSERT INTO account_manager_backup_20260921 (account_id, account_manager_prev)
SELECT a.account_id, a.account_manager
FROM account a
WHERE LOWER(TRIM(COALESCE(a.account_manager, ''))) = 'lara@vintti.com'
ON CONFLICT (account_id) DO NOTHING;

UPDATE account a
SET account_manager = 'pilar@vintti.com'
WHERE LOWER(TRIM(COALESCE(a.account_manager, ''))) = 'lara@vintti.com';

COMMIT;

-- Para revertir:
--   UPDATE account a SET account_manager = b.account_manager_prev
--   FROM account_manager_backup_20260921 b WHERE b.account_id = a.account_id;
