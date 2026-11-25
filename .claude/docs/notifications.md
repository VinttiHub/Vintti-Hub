# Recordatorios y notificaciones

## Perfil incompleto: recordatorio diario hasta completarlo

Cada persona activa (`COALESCE(admin_user_access.is_active, TRUE)`) a la que le falte
**Address, Emergency Contact, Date of Birth o Vintti Start Date** en `docs/profile.html`
recibe un mail en su `email_vintti` cada 24 h, sin CC. Todo en
`backend/utils/profile_completion_reminder.py` (`REQUIRED_FIELDS` es la única lista).

- **El corte es por construcción**: el runner mira `users` en cada corrida; quien guarda los
  4 campos desde su perfil deja de salir solo. `profile_completion_reminders` sólo lleva
  `last_sent_at` (las 24 h) y sella `completed_at` como registro.
- **Vacío incluye `''`**: `profile.js` guarda Emergency Contact en blanco como `''` (los 13
  que faltaban al 2026-09-29 eran todos `''`, ninguno NULL).
- Cron horario `.github/workflows/profile-completion-reminder.yml` →
  `POST /reminders/profile_completion/due` con `X-Audit-Token`; `?dry=1` lista a quién le toca.
  Sábado y domingo (hora Argentina) no manda.
- Modo prueba: `TEST_ONLY_RECIPIENT` en el módulo (hoy `None` = producción, desde el
  2026-09-29). Con un email ahí, todo va sólo a esa dirección con `[TEST]` en el asunto.

## Cumpleaños → calendario "Birthdays/ Team Personal Stuff"

Al guardar **Date of Birth** en `docs/profile.html`, `update_user` (`profile_routes.py`)
dispara, **después del commit y en un hilo**, `sync_birthday_event_async()`: el hub crea el
evento anual (día completo, `transparent`, invita a `team@vintti.com`, título
`Cumple <nombre> :)` para todos: el hub no guarda género) o lo mueve si cambió la fecha. Todo en `backend/utils/birthday_calendar.py`.

- **Escribe con el Google de Jazmín** (`CALENDAR_OWNER_EMAIL`, token de
  `google_calendar_tokens`), no con una cuenta de servicio. Sin su token no se crea nada: el
  panel muestra **Connect Google Calendar** y el mail semanal lo avisa. El calendario se busca
  por nombre en su `calendarList`.
- **Nunca duplica un manual.** Antes de crear busca eventos de cumpleaños (`_BIRTHDAY_RE`) del
  mismo día del año: si el título tiene un prefijo del nombre ("Agos" ⊂ "Agostina") lo
  **adopta** sin tocarlo (`source='adopted'`); si hay uno ese día con otro nombre, o uno con su
  nombre en otro día, queda **review** y no se crea. Un adoptado con fecha distinta tampoco se
  mueve solo: es de Jazmín.
- **Google devuelve cada cumple manual dos veces**: con `singleEvents=False` vienen la serie y
  sus excepciones (una ocurrencia a la que alguien respondió) con `recurringEventId`. Se
  descartan, y dos series iguales el mismo día cuentan como una. Sin eso todos los manuales
  caían en review ("Cumple Agos <3, Cumple Agos <3").
- **Nombres repetidos**: un evento con su nombre en otro día sólo frena si ese día no cumple
  nadie del hub (activo o no); "Cumple Vale" del 18-ago es de otra Valentina. Y un evento del
  MISMO día que nombra a otra persona que cumple ese día es suyo ("Cumple Mia" no frena a
  Benjamin, los dos el 7-mar). Si el nombre/nickname se repite entre activos, el título lleva
  apellido: "Cumple Valentina Cadirola :)" (`_display_name`). Lo que quede en
  review se destraba con **Create anyway** (`POST /birthdays/sync/<id> {"force": true}`).
- **Una baja borra el cumple** (pedido de la owner, 2026-09-30): `_deactivate_endpoint` de
  `admin_routes.py` llama `remove_birthday_event_async()` después del commit. Borra la serie
  entera, **también si era un evento manual**, con `sendUpdates="none"`: desaparece de los
  calendarios de todos sin mandar un "Canceled event" que anuncie la baja. Nunca borra un
  evento registrado a nombre de alguien activo ni uno que nombre a una persona activa que
  cumple ese día. Las bajas anteriores salen en el panel ("No longer at Vintti, still in the
  calendar") con **Remove** y en el mail semanal. No hay ruta de reactivación: si alguien
  vuelve, su cumple se recrea con Create desde el panel.
- Mapeo persona → evento en `birthday_calendar_events` (autocreada). Si borran el evento en
  Google, la fila se suelta sola en el próximo sync.
- Detección: pestaña **Birthdays** de profile.html (sólo `PANEL_EMAILS` = jazmin + pgonzales,
  igual a `BIRTHDAY_PANEL_EMAILS` de profile.js) con los próximos 30 días y quién no tiene
  fecha, + mail semanal a Jazmín (`.github/workflows/birthday-weekly-report.yml` →
  `POST /reminders/birthdays/weekly`, X-Audit-Token; `birthday_report_log` = 1 por semana).
- `POST /birthdays/backfill` es **dry-run por defecto**; el botón "Preview full sync" lo muestra
  y "Create missing events" lo aplica. Arranque: Jazmín conecta → preview → aplicar.

## Slack: opps de Mariano paradas +20 días en Deep Dive / NDA Sent

`backend/utils/stale_opps_slack.py`: un mensaje por día hábil (desde las 09:00 ART) que
menciona a Mariano con las opps suyas (`opp_sales_lead`) que llevan 20 días o más en la
etapa actual — `deep_dive_date` si está en Deep Dive, `nda_sent_date` si está en NDA Sent —
para que las cierre o las mueva. Sin vencidas no se postea nada.

- Cron horario `.github/workflows/stale-opps-slack.yml` →
  `POST /reminders/stale_opps_slack/due` con `X-Audit-Token`; `?dry=1` lista sin postear.
  Un solo mensaje por día lo garantiza `stale_opps_slack_log` (autocreada), reclamada antes
  de postear; si Slack falla se suelta y la próxima corrida reintenta.
- Canal **Sales & Opps** (`SLACK_CHANNEL_ID = "C07GZ8RQWF3"`, hardcodeado, definitivo desde
  el 2026-09-30; antes era el de prueba `C0C0UQ7SYBW`). El bot tiene que estar invitado.

## Slack: opp nueva en Sourcing (sólo la primera vez)

`backend/utils/sourcing_slack.py`: cuando una opp entra a **Sourcing por primera vez** sale un
mensaje a Slack con cliente, puesto, modelo, sales lead (por nombre), start date y **@mención a
la HR lead** (`opp_hr_lead`, vía `daily_digest.people.slack_id`). Lo disparan
`update_opportunity_stage` y el sync de HubSpot (NDA Signed → Sourcing, o opp creada ahí),
siempre después del commit, en un hilo y sin levantar nunca. En `dry_run` no sale.

- Canal **Sales & Opps** (`SLACK_CHANNEL_ID = "C07GZ8RQWF3"`, hardcodeado, definitivo desde
  el 2026-10-16; antes era el de prueba `C0C0UQ7SYBW`). El bot tiene que estar invitado.
- "Primera vez" son dos frenos: `previous_stage` pre-Sourcing (vacío, Deep Dive, NDA Sent) —
  reactivar desde Stop/Closed Lost o volver desde Interviewing **no** avisa — y la tabla
  `sourcing_slack_notified` (una fila por opp, autocreada). Al crearse se **siembra** con todas
  las opps que ya pasaron por Sourcing (stage posterior, start date o fila en `sourcing`), así
  el deploy no avisa por opps viejas.
- Se reclama la fila antes de postear; si Slack falla se suelta (no hay reintento automático).
- **La @mención sale de `slack_id()`** (`daily_digest/people.py`): primero el mapa fijo
  `SLACK_MEMBER_IDS` (cosechado el 2026-09-09) y, si el mail no está, el directorio en vivo
  (`slack.list_members()`, cache 6 h por proceso). Sin ID la persona sale en negrita y **no
  le suena**: le pasaba a las recruiters dadas de alta después del mapa. Si en Slack tiene
  otro mail que en el hub, no hay match: agregarla a mano al mapa.
