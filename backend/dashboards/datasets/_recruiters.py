"""Lista canónica de recruiters (para que los filtros muestren TODOS, aunque no tengan
data en la ventana). Fuente: usuarios con rol 'recruiter' activos (igual que
`/users/recruiters`), excluyendo recruiters inactivos ([[project_turbo_inactive_recruiters]])."""
from __future__ import annotations

# `value` = email (lower) para el filtro; `label` = nickname/nombre para mostrar.
ALL_RECRUITERS_SQL = """
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
      AND LOWER(TRIM(u.email_vintti)) NOT IN ('agustina.barbero@vintti.com', 'jazmin@vintti.com')
    GROUP BY 1, 2
    ORDER BY label
"""

# CTE (sin ORDER BY) para embeber en otras queries: recruiters(email, label).
RECRUITERS_CTE = """
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
        AND LOWER(TRIM(u.email_vintti)) NOT IN ('agustina.barbero@vintti.com', 'jazmin@vintti.com')
      GROUP BY 1, 2
    )
"""
