# Recruitment

## Apriora: las 6 preguntas obligatorias de screening

El botón **Create Job in Apriora** de `docs/opportunity-detail.html` (pestaña Job Description)
crea la entrevista vía `POST /opportunities/<id>/alex/create_position`. Toda entrevista creada
desde el Hub lleva 6 preguntas fijas de screening + el criterio de inglés C1. La definición
única está en **`backend/utils/alex.py::APRIORA_SCREENING_QUESTIONS`**: de ahí salen el template
de Apriora, el fallback por `additionalQuestions` y la verificación posterior. Tocar una lista y
no la otra es el error a evitar.

**`additionalQuestions` es una sugerencia, no un mandato.** La doc de Apriora lo dice literal
("optional free-text questions to *append* to the generated interview") y se comprobó contra las
31 positions que creó el Hub: las reescribe (la opp 799 preguntó "Are you *currently*
participating in other *hiring* processes?"), las intercala aunque se mande
`intelligentlyOrderQuestions=false` (la opp 800 las tiene en las posiciones 1, 2, 3, 6, 7 y 9), y
**a veces dropea una**: la opp 792 quedó sin la de la computadora propia en sus 10 entrevistas.
Es a nivel del guion generado, no algo que Alex saltee por tiempo — todos los candidatos de una
position reciben exactamente las mismas preguntas.

Por eso el camino bueno es un **interview guide template** (`POST /templates`), donde las
preguntas son parte del guion y no sugerencias:

```bash
cd backend
python scripts/create_apriora_template.py            # dry-run: imprime el payload
python scripts/create_apriora_template.py --apply    # lo crea
```

El id que devuelve va a la env **`APRIORA_TEMPLATE_ID`** (`backend/.env` **y** App Runner).
Sin esa env el Hub sigue por el camino viejo, así que un deploy sin setearla no rompe nada —
pero tampoco arregla nada.

Tres cosas que no son obvias:

- **`/templates` sólo tiene GET y POST.** No hay PATCH ni DELETE, y el `name` es único por
  company. Cambiar una pregunta = template nuevo con otro nombre + repuntar la env. Lo mismo
  vale para las positions: `createJob` rechaza `externalJobId` duplicado y no existe update, así
  que una entrevista mal generada sólo se arregla **borrándola a mano en la UI de Apriora** y
  volviéndola a crear desde el botón.
- **Con template no se manda `additionalQuestions`** (se harían dos veces) ni se llama a
  `append_grading_criteria()` sobre la JD: el C1 pasa a ser un `criteria` de verdad, con
  `priority`, en vez de un bloque de texto pegado al final de la job description.
- **`questionLimit` no se setea.** La doc dice que `0` "adds none beyond the template questions":
  pondría en cero las preguntas del rol que Apriora genera desde la JD, que son el grueso de la
  entrevista.

### Verificar que efectivamente las hizo

`GET /opportunities/<id>/alex/question_check` cruza las 6 contra lo que se preguntó de verdad y
lo pinta un badge en la pestaña **Pipeline** (`#apriora-question-check`, lo llena `pipeline.js`).
Dos caminos de match, porque hay dos generaciones de positions:

- **Por tag**, exacto, para las creadas con el template: los nombres de los tags los fijamos
  nosotros. **Un tag sin valor no cuenta**: Apriora lo crea igual y lo deja en `null` cuando la
  pregunta no llegó a hacerse (la opp 776 tiene `US Citizenship = null` y en sus 14 preguntas no
  hay ninguna de ciudadanía).
- **Por texto** (regex sobre `questionSummary`) para las anteriores, calibrado contra las 31
  positions reales. Sin template Apriora **se inventa el nombre del tag en cada entrevista** — la
  misma pregunta salía como "Planned Absences", "Planned Time Off" y "Planned Vacations" — así
  que ahí el tag no sirve de clave.

Sólo se puede responder cuando hay **al menos una entrevista completada**: `questionSummary` no
existe antes, y no hay ningún endpoint que devuelva el guion de una position. Como el guion es
idéntico para todos los candidatos, con el primero alcanza — y conviene, porque arreglarlo
implica rehacer la position. La respuesta se cachea en `app_cache` (1 h con entrevistas hechas,
2 min sin ellas): `list_reports` no está cacheado y el de la opp 792 son 200 KB.

### El fallo del createJob ya no es mudo

_Historia (cómo se notó): ver `.claude/docs/historical-decisions.md` → «createJob mudo (hasta 2026-09-16)»._

Ahora cada intento queda en **`apriora_job_creations`** (`pending` → `ok` | `error`, se autocrea
con `CREATE TABLE IF NOT EXISTS`, sin migración a mano), `GET /opportunities/<id>/alex/create_status`
la expone, y el notificador muestra el error real de Apriora en vez de callarse.

Contexto que conviene tener a mano: de las **348 positions** que hay en Apriora sólo **31** tienen
`externalJobId`, o sea salieron del Hub. Las otras 317 se crearon a mano en la UI y promedian
**2 de 6** preguntas obligatorias. El template las arregla sólo si la recruiter lo elige al crear
la job, o si se lo pone como default de la company — y eso se hace en Apriora, no acá.

## JD Review: el CV Review, pero para la Job Description

> Pendiente de confirmar por la owner (al 2026-09-25): la lista `CHECKLIST_ITEMS` de
> `utils/jd_review_ai.py` y las penalizaciones (5 / tope 20) fueron una propuesta de Claude.
> Cache-bust: `jd-review.css/js`, `jd-review-cards.js` y `jd-review-opp.js` van con `?v=` en
> `jd-review.html`, `opportunity-detail.html` y `recruiter-power.html`.

La JD (`opportunity.hr_job_description`) la escribe gpt-4o desde los transcripts de Grain de la
Intro Call y la Deep Dive (`POST /ai/generate_jd`) y nadie la contrastaba con lo que se habló.
Circuito: la recruiter aprieta **Send JD to review** en la pestaña Job Description de
`docs/opportunity-detail.html` (lógica en `jd-review-opp.js`, aparte de opportunity-detail.js) →
`POST /opportunities/<id>/jd_reviews` congela la JD → un hilo trae los transcripts de los links
guardados en la opp (`first_meeting_recording` / `deepdive_recording`), los congela en
`transcript_snapshot` y scorea → mail al sales lead (o al HR lead) + `OVERSIGHT_EMAILS` → el sales
lead decide en `docs/jd-review.html`.

- Backend: `routes/jd_review_routes.py`, `jd_review_store.py` (tablas `jd_reviews` +
  `jd_review_checklist`, se autocrean como las de cv_reviews), `utils/jd_review_ai.py`.
- **Quién revisa se importa de `cv_review_routes`** (`_require_reviewer`, `OVERSIGHT_EMAILS`): una
  sola lista. En el front, `jd-review.js` y el link del sidebar usan la misma allow-list que CV Review.
- **No hay "rejected"**: una JD no se descarta, se corrige. Aprobar o pedir cambios, con checklist
  obligatorio (ítems de `CHECKLIST_ITEMS` o "clean") y comentario obligatorio al pedir cambios.
- **El juez son dos llamadas separadas a propósito**: primero se extraen los hechos de los
  transcripts SIN ver la JD (para que no se acomode a lo que la JD ya dice), después se juzga cada
  hecho contra la JD (covered / partial / contradicted / missing) + lo que la JD dice y nadie dijo
  (`unsupported`, hard/soft).
- **El número lo calcula `compute_score()`, no el modelo**: core pesa 2, nice 1; partial = medio;
  −5 por contradicción y −5 por requisito inventado "hard" (tope 20 cada uno). El relleno "soft" se
  muestra pero no resta. Subir `ANALYSIS_VERSION` saca los análisis viejos del promedio.
- **La lista de puntos se guarda y se reusa** (tabla `jd_review_facts`, clave = vacante + huella
  de los transcripts + `EXTRACT_VERSION`). Re-extraer en cada corrida agrupaba distinto las tareas
  y el score saltaba ±10 con la misma JD (opp 844: 68 y 80); reusándola, tres corridas dieron 78,
  78, 78. Las rondas siguientes y **Retry the analysis** reusan la lista (Retry sólo aparece si el
  análisis falló o no se pudo leer alguna grabación: sin error daría lo mismo); cambia sola si cambian los links/transcripts,
  y **Rebuild the list of points** (`POST .../analyze {"rebuild": true}`) la rehace a mano.
  **Rebuild re-scorea TODAS las rondas no canceladas de la vacante** contra la lista nueva
  (incluso las ya decididas, y con eso el score del primer envío que usa la métrica): si sólo se
  re-scoreara la actual, la ronda 1 y la 2 quedarían medidas con varas distintas. La lista queda
  firmada (`rebuilt_by` / `rebuilt_at` en `jd_review_facts`) y el drawer lo muestra en ámbar. Lo
  pueden usar los sales leads, no sólo la supervisión (decisión de la owner, 2026-09-25). Si tocás
  el prompt del extractor, subí `EXTRACT_VERSION` o se siguen usando las listas viejas.
- **El salario nunca se exige con monto** (decisión de la owner, 2026-09-25, v2): en la JD no va
  cuánto se gana, así que un punto de salario cuenta como *covered* si la JD menciona la paga de
  cualquier forma ("competitive salary", bonos). Se fuerza en código (`is_salary` + `_SALARY_RE`),
  no sólo en el prompt, porque el juez igual lo marcaba *partial*.
- **El estado de cada punto lo deriva el código, no el juez** (v5, 2026-09-25): el EXTRACTOR parte
  cada punto en partes atómicas ("full-time contractor" = full-time + contractor; una lista = un
  ítem por parte), el juez sólo marca cada parte `explicit` / `implied` / `no`, y
  `derive_status()` decide: todas → covered, algunas → partial, ninguna → missing. Con criterio
  libre (v3) y con el juez partiendo (v4) el mismo caso de la opp 844 salía missing una corrida sí
  y otra no, aunque la JD dijera "9 to 5" (que implica full-time).
- **La cuenta del score la arma `compute_score()`** (`points` / `max_points` / `penalty` por punto,
  `breakdown` / `earned` / `possible` en el resumen) y la página sólo la muestra: no hay una
  segunda copia de la fórmula en el JS.
- Sin links de Grain la ronda se crea igual con `ai_error='no_transcripts'` y el mail lo dice. Si
  el campo del link tiene un transcript pegado (pasó), se usa como texto.
- El popup del AI Assistant ahora precarga los links guardados, y si la opp no los tenía guarda
  los que se usaron para generar (sólo si el campo está vacío).
- **Editar la JD re-califica los CV Reviews `pending` de esa vacante** (2026-09-29, pregunta
  sobre la opp 799). `PATCH /opportunities/<id>/fields` con algún campo del bloque del juez
  llama, después del commit, a `cv_review_routes.rescore_pending_for_opportunity()`: un hilo
  que re-scorea el snapshot enviado sólo si `_jd_hash` difiere de la JD actual (el blur guarda
  aunque no cambie nada). Los decididos **no** se tocan: el score de la 1ª ronda es la métrica
  de la recruiter. Esos siguen con el aviso ámbar + Re-run manual. El bloque lo arma sólo
  `_current_jd_block()`; si se arma distinto en otro lado, la huella deja de ser comparable.
- Métricas: `GET /jd_reviews/metrics` (sección "Per recruiter" de jd-review.html y pestaña **JD
  quality** de Recruiter Power, las dos con la tarjeta de `jd-review-cards.js`). Una vacante cuenta
  una vez, en el período de su primer envío.

## CV con IA: cobertura de la JD y CVs hermanos (2026-10-26)

`POST /generate_resume_fields` se salteaba must-haves y los CVs de una misma vacante salían
clonados ("3 years of Python" en los tres). Ahora, cuando hay vacante, pasa por
`backend/utils/resume_coverage.py`:

1. `build_coverage_map()`: una llamada (gpt-4o, temp 0) lista los **must-haves** de la JD
   (los nice-to-have se cortan con `optional_section_start()`) con su evidencia en las fuentes
   del candidato y sus **años reales**, calculados con las fechas de los roles.
2. El prompt recibe ese checklist y los **CVs hermanos**: lo último generado para esa vacante
   en `resume_generations` (autocreada; fallback: `resume` de los candidatos del pipeline).
3. `check_draft()` revisa sin modelo: tool con evidencia que no aparece en ningún bullet
   (`_tool_find()` de `cv_review_ai.py`), el número de años **del cliente** copiado al CV, y
   frases de 6+ palabras compartidas con un hermano (8+ con la JD). Si falla algo, **una sola**
   pasada de reparación; si la reparación devuelve menos roles, queda el primer borrador.

- **El número de años nunca sale de la JD.** El bloque TARGET ROLE lo etiqueta como umbral
  del cliente, y si el CV dice exactamente ese número y no es el del candidato, se repara.
- **Un must-have sin evidencia no se afirma** (decisión de la owner): sale en el reporte
  `coverage.not_in_sources`, que `renderCoverageReport()` de `candidate-details.js` pinta arriba
  de la pestaña Resume. Si la recruiter sabe que lo tiene, lo agrega en las notas y regenera.
- `"dry_run": true` en el body genera y devuelve sin escribir `resume` ni `resume_generations`.
- Sin vacante, todo esto no corre y el CV sale como antes. Los editores ✨ por sección
  (`/ai/improve_*`) todavía no usan los hermanos.

## Second Interview: recordatorio de referencias cada 24 h

La 6ª columna del Pipeline de `docs/opportunity-detail.html` es **Second Interview**
(`opportunity_candidates.stage_pipeline = 'Segunda entrevista'`, última en `stageOrder` de
`pipeline.js`). Al entrar ahí, `PATCH /opportunities/<id>/candidates/<cid>/stage` llama
`start_second_interview_refs_reminder()` (**después del commit y nunca levanta**) y sale un
mail a `agostina@vintti.com` + `opp_hr_lead` para que pidan y carguen las referencias.
Toda la lógica vive en `backend/utils/second_interview_refs.py`.

- **Se repite cada 24 h hasta que la recruiter marca "References filled"** en la Overview de
  `candidate-details.html` (`candidates.references_filled`, por candidato). También se corta
  si el candidato sale de la columna (`left_stage`). Si vuelve a entrar, la fila se reabre.
- **`references_filled` NO es `check_hr_lead`.** Ese ("All set: resignation letter &
  references") corta el recordatorio de Signed, que pide además la carta de renuncia.
  Reusarlo lo apagaba de antemano (decisión de la owner, 2026-09-29).
- **Cron propio y horario**: `.github/workflows/second-interview-references.yml` →
  `POST /reminders/second_interview_refs/due` con `X-Audit-Token` (= `DASHBOARD_AUDIT_TOKEN`).
  Las 24 h las mide `second_interview_refs_reminders.last_sent_at`, no el cron. No va dentro
  de `/reminders/due` porque ese sólo corre en la ventana 05:00-07:59 de Guatemala y el cron de
  GitHub llega ~4 h tarde: casi nunca manda nada (así está roto hoy el recordatorio de Signed).
- **Sábado y domingo (hora Argentina) no manda**: se posterga al lunes (`alerta_en_pausa()`).
  El primer mail sí sale al instante aunque sea fin de semana, porque lo disparó una persona.
- Un primer envío fallido (`last_sent_at` NULL) se reintenta en la próxima corrida.
- Esquema autocreado (columna + tabla), sin migración a mano. `?dry=1` lista los vencidos.
- Modo prueba: `TEST_ONLY_RECIPIENT` en el módulo (hoy `None` = producción). Con un email ahí,
  todo va sólo a esa dirección con `[TEST]` en el asunto y un aviso de a quién habría ido.

## Mails de referencias: Lara sólo recibe el de las dos

En los dos circuitos (datos de contacto que carga el candidato →
`public_candidate_references_routes.py`; feedback que responden las referencias →
`public_reference_feedback_routes.py`) `lara@vintti.com` va **sólo en los mails que traen las
dos referencias**, re-envíos incluidos — nunca en el de la primera (pedido de la owner,
2026-10-27). La lista es `BOTH_REFERENCES_RECIPIENTS` y se suma con
`with_both_references_recipients()`, deduplicando. **No** está en
`reference_feedback_recipients()`: ese también arma el mail del análisis IA, y ahí no va.

## Postulantes del form web → Sheet → Hub

El form de las vacantes de la web (Webflow, página "Jobs Template") escribe cada postulación en
la pestaña **Formularios** del Sheet `1Jn9xDhu08…` (`IMPORT_SPREADSHEET_ID`), y
`POST /sheets/candidates/import` (`routes/careers_routes.py`) la trae al Hub: busca la vacante por
`Job ID` (opportunity_id o `career_job_id`), encuentra al candidato por mail / LinkedIn / teléfono
o lo crea, y lo suma como **Applicant**. Lo dispara `.github/workflows/sheet-applicants-import.yml`
cada 15 min (desde 2026-11-25, para dejar de gastar créditos de Zapier).

- **Job Submissions es histórica.** Hasta nov-2026 un Zap escribía ahí y llamaba al import por cada
  fila nueva (el endpoint no tiene token por eso). Las dos pestañas tienen las mismas postulaciones
  desde el 31-oct.
- **`ON CONFLICT DO NOTHING`, no `DO UPDATE`.** `sheet_import_log` dedupea por huella **y por gid**:
  al cambiar de pestaña, las filas que ya habían entrado por Job Submissions se re-procesan una vez.
  Con el `DO UPDATE SET stage_pipeline='Applicant'` de antes eso devolvía a Applicant a candidatos
  que la recruiter ya había movido. Consecuencia aceptada: re-postularse a la misma vacante no
  resetea la etapa.
- El gid del log sale del **título real** de la pestaña (`get_sheet_gid_by_title()`, sin fallback a
  la primera pestaña). Para leer otra pestaña: `{"sheet_title": "..."}` en el body o la env
  `IMPORT_SHEET_TITLE`.

## Stop ya no borra la start date (NDA)

Hasta el 2026-10-01, mover una opp a **Stop** en `docs/opportunities.html` hacía
`patchOppFields(id, { nda_signature_or_start_date: null })` (`dispatchStageChange()` en
`main.js`). Al reactivarla se pedía una fecha nueva y la original se perdía sin dejar rastro, y
esa columna es ancla de ~10 datasets. Se notó cuando **NDA → Close Win** de Operations pasó a
excluir las opps sin start date (`data-override-requiere-nda`, filtro `requiere_nda` de los 4
`nda_close_win_*.py`) y se cayeron 582, 623, 624 y 712. Ahora Stop deja la fecha y volver a
Sourcing abre el popup de nueva ronda (`POST /sourcing`).

Las 11 opps afectadas se restauraron con `backend/scripts/restore_nda_dates_stop_20261001.py`.
El valor tipeado no se guardaba en ningún lado: se usó el día (hora ARG) del primer
`saveSourcingDate` en `tracks`, que puede diferir unos días del real. `tracks` arranca en
feb-2026, así que si aparece una opp más vieja sin fecha no hay de dónde sacarla.
