-- ============================================================
-- TCC - Dados iniciais do MVP
-- Banco de dados: PostgreSQL
-- ============================================================

BEGIN;

-- ============================================================
-- CÂMERA INICIAL
-- ============================================================

INSERT INTO cameras (code, name, location, active)
VALUES (
    'camera_1',
    'Câmera 1',
    NULL,
    TRUE
)
ON CONFLICT (code) DO NOTHING;

-- ============================================================
-- EPIs MONITORADOS NO MVP
-- ============================================================

INSERT INTO epis (code, name, description, active)
VALUES
    (
        'helmet',
        'Capacete',
        'Equipamento de proteção para a cabeça.',
        TRUE
    ),
    (
        'vest',
        'Colete',
        'Colete de proteção/identificação utilizado no ambiente monitorado.',
        TRUE
    )
ON CONFLICT (code) DO NOTHING;

-- ============================================================
-- EVENTOS OBSERVACIONAIS
-- ============================================================

INSERT INTO event_types (code, description, epi_id, compliant)
SELECT
    v.code,
    v.description,
    e.id,
    v.compliant
FROM (
    VALUES
        ('pessoa_com_capacete',
         'Pessoa detectada dentro da área de risco utilizando capacete.',
         'helmet',
         TRUE),
        ('pessoa_sem_capacete',
         'Pessoa detectada dentro da área de risco sem capacete.',
         'helmet',
         FALSE),
        ('pessoa_com_colete',
         'Pessoa detectada dentro da área de risco utilizando colete.',
         'vest',
         TRUE),
        ('pessoa_sem_colete',
         'Pessoa detectada dentro da área de risco sem colete.',
         'vest',
         FALSE)
) AS v(code, description, epi_code, compliant)
JOIN epis e
    ON e.code = v.epi_code
ON CONFLICT (code) DO NOTHING;

COMMIT;
