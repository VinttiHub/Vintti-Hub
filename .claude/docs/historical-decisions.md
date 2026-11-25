# Decisiones e incidentes históricos

> Contexto de por qué existen algunas reglas. Las reglas vigentes están en los otros docs;
> acá queda la historia. Las decisiones de la owner con fecha siguen junto a su regla.

## Las 9 opps duplicadas (11–14 sep 2026)

_Regla: `hubspot.md` → «Vincular una opp cerrada la deja cerrada»._

Hasta el 2026-09-14 las cerradas quedaban afuera de `link_candidates` y `/link-deal` las
rechazaba con 409, con el argumento de que el sync no podría moverlas igual. Era al revés:
cuando la gemela Closed Lost era la **única** opp de la cuenta, la lista volvía vacía, el
freno leía esa lista vacía como "no hay nada que consultar" y el sync **creaba en silencio**,
sin mail y sin panel. Así nacieron 9 duplicadas entre el 11 y el 14 de septiembre (Flamingo,
Dolsten, Advisant, Rodgers, Catchy, The Art of Broth, The Email Marketers, Arcady, PQ Meats).

## Fechas que «cambiaban solas» (hasta 2026-09-23)

_Regla: `hubspot.md` → «Fechas de stage»._

Hasta el 2026-09-23 HubSpot pisaba siempre, y eso hacía que las fechas "cambiaran solas".
`hs_v2_date_entered_*` es cuándo el AE hizo click y guarda la **última** entrada, así que:

- El 11-sep se pusieron al día varios deals de una vez en HubSpot y la NDA Signed de la 782
  pasó del 26-ago al 11-sep. Del mismo lote, 730, 761, 788, 795 y 800 tienen 11-sep y la fecha
  real es desconocida: la tiene que confirmar la recruiter.
- El 17-sep, deshacer un push de prueba volvió 8 deals a NDA Signed, y la 780 quedó "firmada" un
  día antes del cierre. Las otras 5 Close Win las restaura
  `backend/scripts/restore_nda_dates_20260917.py`.

## 808 y 825 pasadas a Staffing (2026-09-24)

_Regla: `hubspot.md` → «El Model sigue a HubSpot»._

- **"Todas las opps atadas ya tienen foto" era falso.** La regla de arriba se deployó
  horas después de crear la columna, y el sync es incremental: sólo mira un deal cuando
  alguien lo toca en HubSpot. 808 y 825 quedaron en NULL, el 24-sep se movieron de stage y
  el sync les pisó el Recruiting de la recruiter con Staffing. Parecía que "cambiar de
  stage en HubSpot pasa la opp a Staffing": el stage no era la causa, sólo hizo que el sync
  mirara el deal. El historial de HubSpot (`propertiesWithHistory=model`) muestra que en
  esos deals el Model **siempre** fue Staffing, cargado por el AE en el popup del Deep
  Dive. `backend/scripts/backfill_hubspot_model_seen.py` (dry-run por defecto) saca la
  foto de las que quedaron en NULL sin tocar `opp_model`.

## API_BASE hardcodeada (2026-09-17)

_Regla: `architecture.md` → «La URL de App Runner hardcodeada»._

El síntoma es cruel: la página corre en `localhost`, el backend local está levantado
y **el request se va a producción igual**. Todo "funciona" —el stage cambia, el campo
se guarda— pero lo atendió el código viejo de App Runner. Costó una tarde entera de
debugging del sync inverso: el botón "Enviar a HubSpot" andaba (usa
`candidatesApiBase()`) y el cambio de stage no (iba a prod), y parecía un problema de
proceso local sin reiniciar.

## createJob mudo (hasta 2026-09-16)

_Regla: `recruitment.md` → «El fallo del createJob ya no es mudo»._

`create_position` devuelve **202 antes de que arranque el hilo** que hace el `createJob` (Apriora
tarda ~1-2 min). Hasta el 2026-09-16 la excepción moría en un `logging.warning` y
`apriora-notifier.js` se rendía a los 8 minutos **sin decir nada**, con la lista de pendientes en
`localStorage` (o sea que además moría al cerrar la pestaña). Resultado: la entrevista nunca
creada parecía estar generándose para siempre. Así fue como la opp 790 terminó cargada a mano en
la UI de Apriora sin que nadie supiera que el botón había fallado.

## Reescritura del NRR (2026-09-22)

_Regla vigente: `metrics-and-kpis.md` → «NRR: una sola definición»._

La owner preguntó si el NRR estaba bien calculado. Se auditaron 5 defectos y ella decidió:

| # | Defecto | Decisión |
|---|---|---|
| 1 | El upsell no exige que el hire esté vivo al cierre de la ventana | **NO se toca** |
| 2 | El upsell se valuaba con `ho.salary`/`ho.fee` crudos, fuera del motor canónico | se arregla |
| 3 | No había expansión ni contracción de precio | **se agrega** |
| 4 | El split `downgrades_recorte` / `churn_no_recorte` no cambia el número | **NO se toca** |
| 5 | La card y su drawer no calculaban lo mismo | se arregla |

El punto 3 se decidió midiendo: 19 cambios de precio en 12 meses (18 subidas, 1 baja), +$10.960 GMRR /
+$2.913 fee netos; el sesgo iba siempre para el mismo lado (~0,5 pp/mes, ~6 pp al año).
`upsells_lara` pasó a `upsells`. Antes del cambio de base, al elegir un mes la card daba 103,49 % y el
chart 103,52 %. Tests que tienen que seguir cerrando: card == drawer (los 4 pares).

Efecto de cambios posteriores: buyouts neteados (2026-10-05) → sep-2026 NRR · AM 89,81 % → 91,86 %
(ene-2026 netea $18,1K, lote de 6 buyouts). NRR · AM sobre MRR (2026-10-26) → sep-2026 91,9 % → 92,4 %
(base $220,8K → $65,3K; global GMRR 93,2 %, MRR 93,7 %). end_date + upsell que se va (2026-11-02, caso
Diana Ortiz) → oct-2026 NRR · AM 104,44 % → 100,32 %.
