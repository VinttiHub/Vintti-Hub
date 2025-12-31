BEGIN;

CREATE TABLE IF NOT EXISTS user_roles (
    user_id   INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    role_type TEXT    NOT NULL CHECK (role_type IN ('recruiter', 'sales_lead')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, role_type)
);

-- Seed recruiters based on existing profile data so nobody disappears from the UI.
INSERT INTO user_roles (user_id, role_type)
SELECT DISTINCT u.user_id, 'recruiter'
FROM users u
WHERE (u.role ILIKE '%recruit%')
   OR LOWER(u.email_vintti) IN (
        'pilar@vintti.com',
        'pilar.fernandez@vintti.com',
        'jazmin@vintti.com',
        'agostina@vintti.com',
        'agustina.barbero@vintti.com',
        'agustina.ferrari@vintti.com',
        'josefina@vintti.com',
        'constanza@vintti.com',
        'julieta@vintti.com'
   )
ON CONFLICT DO NOTHING;

-- Seed sales leads using the historic allow list.
INSERT INTO user_roles (user_id, role_type)
SELECT DISTINCT u.user_id, 'sales_lead'
FROM users u
WHERE (u.role ILIKE '%sales%')
   OR LOWER(u.email_vintti) IN (
        'agustin@vintti.com',
        'bahia@vintti.com',
        'lara@vintti.com',
        'mariano@vintti.com'
   )
ON CONFLICT DO NOTHING;

COMMIT;
