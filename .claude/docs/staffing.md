# Staffing

## Staffing: columnas y opciones desde la vista

En `docs/staffing.html` (las 3 pestañas) las 5 personas de `STAFFING_ALLOWED` crean
columnas (lista, texto, número, fecha, Sí/No) y editan las opciones de cualquier
desplegable sin tocar código; los valores se cargan en la celda, tipo Excel. Desde el
2026-10-05 los catálogos ya **no** están en `staffing.js` (quedan sólo como fallback si
`GET /staffing/schema` falla). Todo en `backend/routes/staffing_routes.py`:

- `staffing_options` (catálogo, también el de Platform/Performance/Provider/Exit
  type/Invoice/Paid) y `staffing_columns` (columnas nuevas), autocreadas + seed único
  desde `SEED_OPTIONS`. Sin migración a mano.
- Los valores de las columnas nuevas van en el JSONB `custom` de `staffing_extra`
  (Database y Churn comparten el par) o de `bonus_requests`. Clave = `c_<column_id>`,
  estable aunque se renombre. El PATCH **mezcla** (`custom || ...`), no pisa.
- **Renombrar una opción actualiza las filas** que la tenían, en la misma transacción
  (`BUILTIN_SELECTS` dice dónde vive cada built-in). Ocultar no toca las filas: el valor
  queda y se ve en gris. Ocultar una columna conserva sus valores; se restaura desde
  "Add column".
- **Eliminar** (`DELETE ...?hard=1`, con confirm en el front) sí borra: una opción deja
  vacías las filas que la tenían; una columna se lleva su catálogo y su valor en cada
  fila. Sin vuelta atrás. Las opciones `locked` y las columnas de fábrica no se eliminan.
- `locked`: "Resigned"/"Terminated" y "Paid" sólo se pueden recolorear — los KPIs
  cuentan ese texto y Exit type además se deriva del motivo de baja.
- Colores: paleta cerrada `OPTION_COLORS` ↔ clases `stf-badge--c-<color>` en
  `staffing.css`. Si sumás un color, van los dos.
- Provider no se edita en la celda cuando el equipo trae proveedor
  (`provider_locked`): `equipments.proveedor` gana y el cambio no se vería.

### Email actives (mails a los contractors activos)

Botón **Email actives** en la pestaña Database de `docs/staffing.html`, sólo para
pgonzales, jazmin y lara (`STAFFING_MAIL_ALLOWED` en `staffing_routes.py`, `MAIL_ALLOWED` en
`staffing.js`; Agustín y Pilar ven Staffing pero no esto). Lista con copiar todos / uno a uno
(`GET /staffing/active-emails`) y envío desde el hub (`POST /staffing/send-email`).

- "Activo" es el `status` de la pestaña (`_fetch_pairs`), deduplicado por mail. No hay otra query.
  El modal arranca con **Onboarding incluido** (= el tile "Active" de la pestaña, pedido de la
  owner 2026-10-13); el tilde "Include onboarding" lo saca.
- **El mail del destinatario lo resuelve el servidor desde el candidate_id** y re-chequea que
  siga activo: el navegador nunca manda una dirección.
- Un mail por persona (nunca un `to` masivo); `{nombre}` = primer nombre; cada persona puede
  tener su texto editado. Reply-to = quien lo manda (`reply_to` nuevo y opcional en
  `/send_email`; aplica recién con el backend deployado, porque `post_transactional_email`
  pega a prod). Registro en `staffing_email_log` (autocreada). `TEST_ONLY_RECIPIENT` para pruebas.

### Prorrateo (Days worked / Prorated salary / Prorated fee)

Pestaña Database, selector **Payroll month** (default = mes en curso). Todo en el front
(`proration()` / `prorate()` en `staffing.js`), sin endpoint:

- Días hábiles = **lunes a viernes, sin feriados**, start y end **inclusive**.
- `hábiles trabajados en el mes / hábiles del mes × salary` (y × fee). Ej.: nov-2026 = 21;
  entra el 16 → 11/21 × $500 = $261.90. Sin end = trabaja hasta fin de mes.
- Sin start_date o contrato fuera del mes → `—`. Mes completo = 100%.
- El total del pie de las dos columnas prorrateadas suma **también Inactive** (`totalAll`):
  quien se fue a mitad de mes se paga. El resto del pie sigue siendo "Active total".
- El CSV (`/staffing/database.csv?month=YYYY-MM`) trae Days worked / Prorated salary / Prorated fee
  del mes elegido. Lo calcula `_proration()` en `staffing_routes.py`: **mismo cálculo que
  `proration()` del JS**, si tocás uno tocá el otro. Los KPIs no incluyen el prorrateo.
