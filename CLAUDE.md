# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository shape

Three deployables live side-by-side, and understanding which one you're touching is the single most important thing:

- **`backend/`** — Flask API (Python). Deployed on AWS App Runner at `https://7m6mw95m8y.us-east-2.awsapprunner.com`. Both the legacy `docs/` site and the new React SPA call this same origin.
- **`frontend/`** — Vite + React 19 SPA. The eventual replacement for `docs/`. Entry at `src/main.jsx` → `src/App.jsx`.
- **`docs/`** — Legacy static HTML/CSS/vanilla-JS site served via GitHub Pages at `vinttihub.vintti.com` (see root `CNAME`). Being migrated page-by-page into the React app; both coexist in production today.

The React SPA deliberately reuses `docs/assets/css/style.css` and keeps the same element IDs/classes so styling is shared during migration. `src/hooks/usePageStylesheet.js` dynamically injects a `<link>` per page for this purpose. When porting a page, preserve IDs/classes and translate the paired `docs/assets/js/<page>.js` into hooks/effects — see `frontend/README.md` for the full migration recipe.


## Documentación por tema (leer bajo demanda)

Este archivo tiene sólo lo esencial. El detalle vive en `.claude/docs/` y **no se carga solo**:
antes de tocar un módulo, leé su doc. Si cambiás una regla, actualizá el doc correspondiente.

| Doc | Cuándo leerlo |
|---|---|
| `.claude/docs/architecture.md` | rutas Flask (blueprints vs `register_*`), integraciones, CORS, frontend, `API_BASE`, sidebar por rol |
| `.claude/docs/database-schema.md` | conexión a RDS, migraciones, convenciones de columnas y trampas del esquema |
| `.claude/docs/deployment.md` | comandos, App Runner, env vars, inventario de crons |
| `.claude/docs/metrics-and-kpis.md` | `docs/dashboard.html`: auditor, libro de hechos, NRR, paleta |
| `.claude/docs/hubspot.md` | sync HubSpot → opps, push hub → HubSpot, Account Details → HubSpot, corte de HubSpot |
| `.claude/docs/prospecting.md` | Prospecting: acceso, Clay, contactos, Calendly, sync HubSpot, negocios, vistas, paneles, propiedades |
| `.claude/docs/prospecting-workflows.md` | motor de workflows, reglas/operadores, acciones, carpetas, lienzo |
| `.claude/docs/recruitment.md` | Apriora, JD Review, CV con IA, Second Interview, referencias, postulantes, Stop/start date |
| `.claude/docs/staffing.md` | `docs/staffing.html`: columnas editables, Email actives |
| `.claude/docs/notifications.md` | perfil incompleto, cumpleaños → Calendar, Slack de opps estancadas y de Sourcing |
| `.claude/docs/historical-decisions.md` | incidentes que explican por qué existen algunas reglas |

## Reglas que no se rompen

- **No tocar `frontend/`** ni nada de React. Todo el trabajo va en `backend/` y `docs/`.
- **Nunca poner un `.md` de documentación dentro de `docs/`**: es el sitio público de GitHub Pages.
- `backend/db.py` lee el password de RDS de la env `RDS_PASSWORD` (`backend/.env` en local, App
  Runner en prod), sin fallback: nunca volver a escribirlo en el código (el repo es público) ni
  imprimirlo en logs o errores. Host/puerto/usuario/db tienen default con env `RDS_*`. Cada ruta abre y cierra su conexión (sin pool ni ORM).
  RDS tiene `max_connections=81`.
- **CORS**: sólo `https://vinttihub.vintti.com` (+ `localhost:5500` / `127.0.0.1:5500` en `after_request`).
  No ampliarlo en un commit.
- **Fetch nuevo en `docs/` → `${API_BASE}` / `candidatesApiBase()`**, nunca la URL de App Runner
  escrita a mano (manda las pruebas locales a prod). Única excepción: `SEND_EMAIL_ENDPOINT`.
- **App Runner corre Python 3.8**: nada de `zoneinfo` ni sintaxis 3.9+.
- Dependencia nueva de backend → en los **dos** `requirements.txt` (raíz pinneado, `backend/` suelto).
- `init_services()` inicializa OpenAI/Affinda/S3: nada que los use puede bindearse al importar.
  Una env var faltante deja el cliente en `None` (AttributeError al usarlo).
- **Destinatarios de mails hardcodeados** (`RECIPIENTS`, `TEST_ONLY_RECIPIENT`, listas de acceso):
  se cambian sólo a pedido de la owner (`pgonzales@vintti.com`). Mails de prueba sólo a ella.
- Al editar JS/CSS de `docs/`, subir el `?v=` del include en el `.html` correspondiente.
- No commitear: los commits y el push los hace la owner.

## Patrones del repo (usarlos igual en código nuevo)

- **Tablas autocreadas**: lo nuevo usa `CREATE TABLE/ADD COLUMN IF NOT EXISTS` en el primer uso,
  sin migración a mano. Las migraciones viejas de `backend/sql/` se corren a mano en RDS.
- **Efectos secundarios después del commit**: mails, Slack, push a HubSpot y Calendar van FUERA del
  `with conn:`, en un hilo, y **nunca levantan**. Adentro, un error externo haría rollback de lo
  que la persona ya guardó.
- **Crons**: GitHub Actions → `POST` con `X-Audit-Token` (= `DASHBOARD_AUDIT_TOKEN`), `?dry=1` para
  ver sin escribir. Llegan con horas de atraso: corren cada hora y deciden con su propia tabla
  (`last_sent_at`, claim con `UPDATE … RETURNING`).
- **Sábado y domingo (hora Argentina, `today_ar()` / `alerta_en_pausa()`) no se avisa**: se posterga
  al lunes, sin perder el aviso. Un primer envío disparado por una persona sí sale.
- **Modo prueba**: `TEST_ONLY_RECIPIENT` en el módulo (`None` = producción).
- **Vacío incluye `''`**: el blur de `docs/` guarda string vacío. Usar `NULLIF(col,'')`.
- **«HubSpot gana sólo cuando cambia»**: foto del último valor visto (`*_seen`). Lo que corrigió una
  persona en el hub no se pisa en cada corrida.
- **Sugerencia + un click, nunca adivinar**: emparejamientos y montos dudosos se muestran a una
  persona y los aplica ella (vincular deals, montos de Closed Win, links de candidatos).
- **psycopg2**: un `%` literal en el SQL (incluso en un comentario) rompe la query. Con
  `RealDictCursor`, desempaquetar una fila da las claves, no los valores.

## Invariantes por módulo (el detalle, en el doc de cada uno)

**Dashboards** (`metrics-and-kpis.md`)
- `backend/dashboards/audit/reduce.py` es port 1:1 de `reduce()` de `control-dashboard.js:873`: si tocás uno, tocá el otro.
- El NRR se escribe **una sola vez**, en `backend/dashboards/datasets/_nrr_decomp.py`. Card y drawer salen del mismo CTE.
- NRR · AM = MRR (fee) fijo. El NRR global lleva `data-override-metric` en todo elemento.
- Un `_detail.py` de drawer usa `window_bounds()` igual que su card.
- Sales tab: filtrar `opp_sales_lead` a Mariano + Bahía.
- Paleta de marca: blue `#003bff`, violet `#6c38ff`, lime `#c1ff72` («green» siempre es lime, con texto oscuro encima), cyan `#4ba9ff`, magenta `#ff1fdb`. Sólo esas cinco, con sombras vía `color-mix`.

**HubSpot** (`hubspot.md`)
- Una opp con `hubspot_deal_id` NULL **no la toca nunca** el sync: todo UPDATE lleva `AND NULLIF(hubspot_deal_id,'') IS NOT NULL`.
- El sync no retrocede stages (`decide_stage_transition()`, `decide_push_stage()`) ni reabre Closed Lost/Stop. No hardcodea stage ids.
- Columna nueva para el sync → un `_ensure_*` propio, nunca en `_ensure_hubspot_opportunity_columns()` (se cortocircuita en prod).
- El sync no escribe `hire_opportunity` ni `salary_updates`. `utils/hubspot_push_values.py` replica la precedencia de `_mrr_staffing.py:79-95`: si se toca uno, se toca el otro.
- El corte del SQL (2026-10-05) vive en `utils/hubspot_opportunities.py::SQL_DATE_CUTOVER` y `_sql_anchor.py::SQL_CUTOVER` (`_mkt_sql_anchor.py` importa este último).
- Push apagado por defecto (`HUBSPOT_PUSH_ENABLED`, con D). `ACCOUNT_EDITORS` está en `accounts_routes.py` y `account-details.js`.
- Corte de HubSpot: cuando la owner diga «prendé el interruptor», seguir la checklist de `hubspot.md`.

**Prospecting** (`prospecting.md`, `prospecting-workflows.md`)
- Condiciones: `rules.py` compila a SQL y evalúa en Python. **Las dos tienen que dar lo mismo** (test de paridad).
- `properties.refresh()` reconstruye en el lugar `FIELDS`, `CONTACT_FIELDS`, `DEAL_FIELDS`…: no copiarlos a otra estructura al importar.
- `engine.BatchCursor` difiere escrituras: si leés el resultado de una, ponele `RETURNING`.
- `tick()` sin alcance es la corrida global: nunca pasar `company_id=None` esperando «ese contacto».
- Una dummy nunca le escribe a una persona real. Los filtros/operadores replican el doc de la owner.

**Recruitment** (`recruitment.md`)
- Las 6 preguntas de Apriora se definen sólo en `utils/alex.py::APRIORA_SCREENING_QUESTIONS`.
- JD Review: el score lo calcula `compute_score()`, no el modelo. Si cambia el prompt del extractor, subir `EXTRACT_VERSION`.
- Las métricas definen «contratado» por la fila en `hire_opportunity`, nunca por `opp_stage`.

**Staffing** (`staffing.md`): los catálogos viven en `staffing_options`, no en `staffing.js`. Las opciones `locked` sólo se recolorean.
