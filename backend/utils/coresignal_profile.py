"""Lectura del payload de Coresignal: los helpers que comparten Hirex sourcing y CV Review.

Coresignal cambia la forma según el endpoint (employee_base vs employee_clean) y según qué
tan completo esté el perfil, así que todo campo se busca a la defensiva. Vivían dentro de
routes/hirex_sourcing_routes.py; se mudaron acá cuando el CV Review empezó a comparar el CV
contra el LinkedIn, para no tener dos copias que se separen.
"""
import datetime as _dt
import json
from typing import Any, Dict, List, Optional


def pick(data, *keys):
    """First non-empty value among `keys`. Coresignal's shape varies by endpoint
    and by how complete a profile is, so every field is looked up defensively."""
    for key in keys:
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, (int, float)):
            return str(value)
    return None


def experiences(profile):
    for key in ("experience", "member_experience_collection", "experiences",
                "member_experience", "work_experience"):
        value = profile.get(key)
        if isinstance(value, list) and value:
            return value
    return []


def alive(items):
    """Coresignal keeps tombstones; anything flagged deleted is history, not fact."""
    return [i for i in items if isinstance(i, dict) and not i.get("deleted")]


def period_bounds(item):
    """(inicio, fin) como texto, con "Present" si el rol sigue en curso."""
    start = pick(item, "date_from") or (str(item["date_from_year"]) if item.get("date_from_year") else None)
    end = pick(item, "date_to") or (str(item["date_to_year"]) if item.get("date_to_year") else None)
    if item.get("is_current") in (1, True, "1") and not end:
        end = "Present"
    return start, end


def period(item):
    start, end = period_bounds(item)
    if start and end:
        return f"{start} – {end}"
    return start or end


def load_profile(raw: Any) -> Optional[Dict[str, Any]]:
    """`candidates.coresignal_scrapper` es TEXTO con el JSON adentro. None si no se lee."""
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return None
    if isinstance(data, list) and data and isinstance(data[0], dict):
        data = data[0]
    return data if isinstance(data, dict) else None


def work_roles(profile: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Los roles vivos del perfil, en el orden en que los da Coresignal (más nuevo primero)."""
    out = []
    for item in alive(experiences(profile)):
        title = pick(item, "title", "position", "job_title")
        company = pick(item, "company_name", "company", "organization")
        if not (title or company):
            continue
        start, end = period_bounds(item)
        current = (item.get("is_current") in (1, True, "1")
                   or item.get("active_experience") in (1, True, "1")
                   or (end or "").lower() == "present")
        out.append({"title": title or "", "company": company or "",
                    "start": start or "", "end": "" if current else (end or ""),
                    "current": bool(current)})
    return out


def profile_as_of(profile: Dict[str, Any]) -> Optional[_dt.date]:
    """De cuándo es la copia del perfil que tiene Coresignal. NO es cuándo la bajamos:
    Coresignal guarda su propia copia y puede tener meses aunque la pidamos hoy."""
    for key in ("checked_at", "updated_at", "last_updated", "created_at"):
        raw = str(profile.get(key) or "")[:10]
        try:
            return _dt.date.fromisoformat(raw)
        except ValueError:
            continue
    return None
