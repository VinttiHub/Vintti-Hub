# Vintti Hub: guía para entrar a trabajar en el código

Guía para alguien que tiene que poder arreglar algo y subirlo a producción sin ayuda.
El detalle de cada módulo está en `CLAUDE.md`, en la raíz del repo. Leelo antes de tocar un área.

## Cómo está armado

| Parte | Qué es | Cómo llega a producción |
|---|---|---|
| `docs/` | El Hub que usa todo el equipo: HTML, CSS y JavaScript sin framework | GitHub Pages (`vinttihub.vintti.com`). Se publica solo al hacer push a `main` |
| `backend/` | API en Flask (Python) | AWS App Runner (`https://7m6mw95m8y.us-east-2.awsapprunner.com`). Se deploya al hacer push a `main` |
| `.github/workflows/` | Crons: syncs de HubSpot, recordatorios, el auditor del dashboard… | GitHub Actions |
| `frontend/` | App en React que hoy no se usa | **No tocar** |

**Hacer push a `main` es mandarlo a producción.** No hay entorno de staging.

## 1. Accesos que tenés que pedir

- [ ] **GitHub**: tu propia cuenta, invitada a la organización `VinttiHub` con permiso de **Write** sobre `Vintti-Hub`.
- [ ] **AWS** (región us-east-2): tu propio usuario, para ver logs y deploys de App Runner y poder hacer Redeploy.
- [ ] **`backend/.env`**: el archivo con las claves. No está en git y llega por un canal seguro (gestor de contraseñas). **Nunca lo subas al repo, ni por Slack ni por mail.**
- [ ] Un usuario del Hub con permisos de admin, para probar.
- [ ] Si hace falta: HubSpot, Google Cloud, Slack, SendGrid y Cloudflare (dominio).

## 2. Qué instalar

- **Git**: en Mac, `xcode-select --install`. Después:
  `git config --global user.name "Tu Nombre"` y `git config --global user.email "vos@vintti.com"`.
- **GitHub CLI**: `brew install gh` y después `gh auth login`. (Sirve también GitHub Desktop.)
- **VS Code**, con las extensiones **Python** y **Live Server**.
- **Python 3** (python.org o `brew install python`).
- Opcional: **Claude Code**. Ya conoce el repo porque lee `CLAUDE.md`.

No hace falta Node.

## 3. Puesta en marcha (una sola vez)

```bash
git clone https://github.com/VinttiHub/Vintti-Hub.git
cd Vintti-Hub/backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
# poné el .env que te pasaron en backend/.env
python app.py          # el backend queda andando en http://127.0.0.1:5000
```

El Hub: abrí la carpeta `Vintti-Hub` en VS Code, botón derecho sobre un HTML de `docs/` →
**Open with Live Server**. Tiene que abrir en el puerto **5500**, porque el backend sólo
acepta pedidos de ese puerto en local.

Cada vez que abras una terminal nueva: `cd Vintti-Hub/backend && source .venv/bin/activate`.

## 4. El día a día

```bash
git pull                       # traer lo último antes de empezar
# ... cambios ...
git status                     # ver qué tocaste
git add <archivos>
git commit -m "Qué arreglé"
git push                       # = producción
```

Si después de un push algo se rompe, deshacelo:

```bash
git log --oneline -5           # buscar el commit
git revert <id-del-commit>
git push
```

Los deploys del backend se siguen en la consola de AWS → App Runner. Los crons se miran en la
pestaña **Actions** del repo en GitHub.

## 5. Cosas que hay que saber sí o sí

- **El backend local usa la base de datos de producción.** No hay base de prueba: lo que guardes probando en local queda guardado de verdad. Probá con datos de prueba (cuando los hay) o con mucho cuidado.
- **Producción corre Python 3.8.** No uses nada de 3.9 en adelante (`zoneinfo`, `list[str]` en anotaciones, `match`): App Runner no arranca y se queda en la versión anterior. Síntoma típico: la ruta nueva responde 404.
- **Caché del navegador**: si editás un `.js` o `.css` de `docs/`, subí el `?v=` donde ese HTML lo incluye (por ejemplo `main.js?v=123` → `?v=124`). Si no, el navegador sigue usando el viejo.
- **Fetch nuevos en `docs/`**: usá `API_BASE`, nunca la URL de App Runner escrita a mano. Si la escribís, la prueba local le pega a producción.
- **Migraciones**: los `.sql` de `backend/sql/` se corren a mano contra la base. La mayoría de las tablas nuevas se crean solas al arrancar.
- **Dependencias de Python**: si agregás una, va en los **dos** `requirements.txt` (el de la raíz y el de `backend/`).
- **Credenciales**: las de `backend/db.py` están escritas en el archivo. No las imprimas en logs ni las pegues en ningún lado.
- Mails y Slack: varias funciones mandan mensajes reales. Antes de probar una, revisá a quién le escribe.
