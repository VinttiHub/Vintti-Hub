"""Helpers de estado de contratación compartidos entre routes.

Viven acá (y no en accounts_routes/candidates_routes) porque los dos módulos
necesitan la misma limpieza y no pueden importarse entre sí.
"""
import logging


def clear_stale_hire_for_opportunity(cursor, opportunity_id, keep_candidate_id):
    """Deshace la contratación de cualquier OTRO candidato de esta opportunity.

    Caso real que motiva esto (opp 669): el candidato A llega a Signed, se le
    carga la pestaña Hire (start_date, carga_active, salary, fee) y después se
    cae; el puesto se lo lleva el candidato B. `candidato_contratado` pasa a B,
    pero la fila de A queda con fechas y sigue contando como contractor activo
    en TODOS los datasets de dashboard — que nunca miran `opp_stage` ni
    `candidato_contratado`, solo `hire_opportunity` + `start_d` + sin `end_d`.
    Además el chip de Condition en candidates.html lo muestra como "active".

    Ojo con dos cosas:
    - NO borra la fila: el formulario público de referencias escribe ahí
      (reference_1_*, etc.) incluso para candidatos que no fueron contratados.
      Limpiar las fechas alcanza — los datasets filtran por start_d IS NOT NULL.
    - Solo toca filas con `end_date IS NULL`. Una fila con end_date es una
      contratación real que después churneó (ej. opp 478); esa historia se
      respeta.
    """
    if not opportunity_id or not keep_candidate_id:
        return 0

    cursor.execute(
        """
        UPDATE hire_opportunity
           SET carga_active = NULL,
               start_date = NULL
         WHERE opportunity_id = %s
           AND candidate_id <> %s
           AND end_date IS NULL
           AND (
                 carga_active IS NOT NULL
                 OR NULLIF(TRIM(CAST(start_date AS TEXT)), '') IS NOT NULL
           )
        """,
        (opportunity_id, keep_candidate_id),
    )
    cleared = cursor.rowcount or 0

    cursor.execute(
        """
        UPDATE candidates_batches cb
           SET status = NULL
         WHERE cb.candidate_id <> %s
           AND cb.status = 'Candidate hired'
           AND EXISTS (
                 SELECT 1
                   FROM batch b
                  WHERE b.batch_id = cb.batch_id
                    AND b.opportunity_id = %s
           )
        """,
        (keep_candidate_id, opportunity_id),
    )

    if cleared:
        logging.info(
            "🧹 Hire previo limpiado en opportunity_id=%s (%s fila/s), se mantiene candidate_id=%s",
            opportunity_id,
            cleared,
            keep_candidate_id,
        )
    return cleared
