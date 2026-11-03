"""Carpetas de workflows de Prospecting (como las de HubSpot).

Anidadas: `prospect_wf_folders.parent_id` (NULL = raíz) y `prospect_workflows.folder_id`
(NULL = raíz). Las tablas las crea store.ensure_schema().

Reglas:
  * nombre obligatorio (≤ 120) y único entre hermanas, sin distinguir mayúsculas;
  * una carpeta no se puede mover adentro de sí misma ni de una descendiente;
  * borrar una carpeta NUNCA borra workflows: su contenido (workflows y subcarpetas)
    sube a la carpeta de arriba.
"""
from __future__ import annotations

from prospecting.rules import parse_int

MAX_NAME = 120


class FolderError(ValueError):
    """Error de validación con un mensaje para mostrar tal cual."""


def clean_folder_id(cur, v):
    """None (raíz) o el id de una carpeta que existe."""
    if v in (None, "", "root"):
        return None
    fid = parse_int(v)
    if fid is None:
        raise FolderError("Carpeta inválida.")
    cur.execute("SELECT 1 FROM prospect_wf_folders WHERE id = %s", (fid,))
    if cur.fetchone() is None:
        raise FolderError("Esa carpeta ya no existe.")
    return fid


def list_folders(cur) -> list[dict]:
    cur.execute(
        """
        SELECT f.id, f.name, f.parent_id, f.created_by, f.created_at, f.updated_at,
               (SELECT COUNT(*) FROM prospect_workflows w WHERE w.folder_id = f.id) AS workflows
          FROM prospect_wf_folders f
         ORDER BY LOWER(f.name), f.id
        """
    )
    return [dict(r) for r in cur.fetchall()]


def _get(cur, fid: int) -> dict | None:
    cur.execute("SELECT id, name, parent_id FROM prospect_wf_folders WHERE id = %s", (fid,))
    r = cur.fetchone()
    return dict(r) if r else None


def _clean_name(cur, name, parent_id, self_id=None) -> str:
    name = " ".join((name or "").split())
    if not name:
        raise FolderError("Ponele un nombre a la carpeta.")
    if len(name) > MAX_NAME:
        raise FolderError(f"El nombre es muy largo (máximo {MAX_NAME} caracteres).")
    cur.execute(
        """
        SELECT 1 FROM prospect_wf_folders
         WHERE LOWER(name) = LOWER(%s) AND parent_id IS NOT DISTINCT FROM %s AND id <> %s
        """,
        (name, parent_id, self_id or 0),
    )
    if cur.fetchone():
        raise FolderError(f"Ya hay una carpeta «{name}» ahí.")
    return name


def _descendants(cur, fid: int) -> set[int]:
    """La carpeta y todas las que cuelgan de ella."""
    cur.execute(
        """
        WITH RECURSIVE t AS (
            SELECT id FROM prospect_wf_folders WHERE id = %s
            UNION
            SELECT f.id FROM prospect_wf_folders f JOIN t ON f.parent_id = t.id
        )
        SELECT id FROM t
        """,
        (fid,),
    )
    return {r["id"] for r in cur.fetchall()}


def create_folder(cur, name, parent_id, actor: str | None) -> dict:
    parent_id = clean_folder_id(cur, parent_id)
    name = _clean_name(cur, name, parent_id)
    cur.execute(
        "INSERT INTO prospect_wf_folders (name, parent_id, created_by) VALUES (%s, %s, %s) RETURNING id",
        (name, parent_id, actor),
    )
    fid = cur.fetchone()["id"]
    return {**_get(cur, fid), "workflows": 0}


def update_folder(cur, fid: int, body: dict) -> dict | None:
    """Renombrar (`name`) y/o mover (`parent_id`; null = raíz)."""
    cur_f = _get(cur, fid)
    if cur_f is None:
        return None
    parent_id = cur_f["parent_id"]
    if "parent_id" in body:
        parent_id = clean_folder_id(cur, body.get("parent_id"))
        if parent_id is not None and parent_id in _descendants(cur, fid):
            raise FolderError("No se puede mover una carpeta adentro de sí misma.")
    name = body.get("name", cur_f["name"])
    name = _clean_name(cur, name, parent_id, self_id=fid)
    cur.execute(
        "UPDATE prospect_wf_folders SET name = %s, parent_id = %s, updated_at = NOW() WHERE id = %s",
        (name, parent_id, fid),
    )
    return _get(cur, fid)


def delete_folder(cur, fid: int) -> dict | None:
    """Borra la carpeta; sus workflows y subcarpetas pasan a la carpeta de arriba."""
    f = _get(cur, fid)
    if f is None:
        return None
    parent = f["parent_id"]
    cur.execute("UPDATE prospect_workflows SET folder_id = %s WHERE folder_id = %s RETURNING id", (parent, fid))
    moved_wf = len(cur.fetchall())
    # Subcarpetas que suben: si chocan de nombre con una hermana de arriba, se les suma
    # el nombre de la carpeta borrada para no dejar dos iguales.
    cur.execute("SELECT id, name FROM prospect_wf_folders WHERE parent_id = %s", (fid,))
    children = [dict(r) for r in cur.fetchall()]
    for ch in children:
        cur.execute(
            """
            SELECT 1 FROM prospect_wf_folders
             WHERE LOWER(name) = LOWER(%s) AND parent_id IS NOT DISTINCT FROM %s AND id <> %s
            """,
            (ch["name"], parent, ch["id"]),
        )
        new_name = f"{ch['name']} ({f['name']})"[:MAX_NAME] if cur.fetchone() else ch["name"]
        cur.execute(
            "UPDATE prospect_wf_folders SET parent_id = %s, name = %s, updated_at = NOW() WHERE id = %s",
            (parent, new_name, ch["id"]),
        )
    cur.execute("DELETE FROM prospect_wf_folders WHERE id = %s", (fid,))
    return {"deleted": True, "moved_workflows": moved_wf, "moved_folders": len(children), "to": parent}


def move_workflows(cur, ids, folder_id) -> int:
    if not isinstance(ids, list) or not ids:
        raise FolderError("Elegí qué workflows mover.")
    wf_ids = [parse_int(x) for x in ids]
    if any(x is None for x in wf_ids):
        raise FolderError("Hay un workflow inválido.")
    folder_id = clean_folder_id(cur, folder_id)
    cur.execute(
        "UPDATE prospect_workflows SET folder_id = %s WHERE id = ANY(%s) RETURNING id",
        (folder_id, wf_ids),
    )
    return len(cur.fetchall())
