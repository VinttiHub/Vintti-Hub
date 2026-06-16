-- Unifica el canal de origen "Events" (plural, dato viejo) con "Event" (singular),
-- que es el valor oficial de la propiedad `origin` en HubSpot. Así las métricas que
-- agrupan por account.where_come_from coinciden con los conteos MQL/SQL que vienen
-- de HubSpot (donde se normaliza a "Event"). Ver _normalize_lead_source.
UPDATE account
SET where_come_from = 'Event'
WHERE TRIM(where_come_from) = 'Events';
