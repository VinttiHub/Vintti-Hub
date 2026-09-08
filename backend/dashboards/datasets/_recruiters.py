"""Lista canónica de recruiters (para que los filtros muestren TODOS, aunque no tengan
data en la ventana). Fuente: usuarios con rol 'recruiter' activos (igual que
`/users/recruiters`), excluyendo recruiters inactivos ([[project_turbo_inactive_recruiters]])."""
from __future__ import annotations

# Ex-empleadas: siguen teniendo filas históricas, pero no son "recruiters activos".
# Vive acá y se interpola en las tres queries de abajo para que no haya tres listas
# que puedan separarse: el día que alguien se va, se toca UNA línea.
INACTIVE_RECRUITERS = ("agustina.barbero@vintti.com", "jazmin@vintti.com")

_EXCLUDE = ", ".join(f"'{email}'" for email in INACTIVE_RECRUITERS)

# `value` = email (lower) para el filtro; `label` = nickname/nombre para mostrar.
ALL_RECRUITERS_SQL = f"""
    SELECT
      LOWER(TRIM(u.email_vintti)) AS value,
      COALESCE(NULLIF(TRIM(u.nickname), ''),
               NULLIF(TRIM(u.user_name), ''),
               u.email_vintti) AS label,
      0::int AS count
    FROM user_roles ur
    JOIN users u ON u.user_id = ur.user_id
    LEFT JOIN admin_user_access aua ON aua.user_id = u.user_id
    WHERE ur.role_type = 'recruiter'
      AND COALESCE(aua.is_active, TRUE)
      AND NULLIF(TRIM(u.email_vintti), '') IS NOT NULL
      AND LOWER(TRIM(u.email_vintti)) NOT IN ({_EXCLUDE})
    GROUP BY 1, 2
    ORDER BY label
"""

# CTE (sin ORDER BY) para embeber en otras queries: recruiters(email, label).
RECRUITERS_CTE = f"""
    recruiters AS (
      SELECT
        LOWER(TRIM(u.email_vintti)) AS email,
        COALESCE(NULLIF(TRIM(u.nickname), ''),
                 NULLIF(TRIM(u.user_name), ''),
                 u.email_vintti) AS label
      FROM user_roles ur
      JOIN users u ON u.user_id = ur.user_id
      LEFT JOIN admin_user_access aua ON aua.user_id = u.user_id
      WHERE ur.role_type = 'recruiter'
        AND COALESCE(aua.is_active, TRUE)
        AND NULLIF(TRIM(u.email_vintti), '') IS NOT NULL
        AND LOWER(TRIM(u.email_vintti)) NOT IN ({_EXCLUDE})
      GROUP BY 1, 2
    )
"""

# user_id + email. Lo usa el sync de turbos (backend/routes/turvo_routes.py) para saber
# qué calendarios de Google escanear. Comparte criterio con las dos de arriba a
# propósito: si la lista del sync y la del dashboard se separan, el dashboard cuenta
# turbos de gente cuyo calendario nadie está mirando — que es exactamente el agujero
# que dejó a la pestaña Ops sin datos entre 2026-08-06 y 2026-09-08.
RECRUITERS_WITH_ID_SQL = f"""
    SELECT DISTINCT
      u.user_id,
      LOWER(TRIM(u.email_vintti)) AS email
    FROM user_roles ur
    JOIN users u ON u.user_id = ur.user_id
    LEFT JOIN admin_user_access aua ON aua.user_id = u.user_id
    WHERE ur.role_type = 'recruiter'
      AND COALESCE(aua.is_active, TRUE)
      AND NULLIF(TRIM(u.email_vintti), '') IS NOT NULL
      AND LOWER(TRIM(u.email_vintti)) NOT IN ({_EXCLUDE})
    ORDER BY email
"""
