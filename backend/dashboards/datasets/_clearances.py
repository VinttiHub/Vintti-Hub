"""Predicado compartido: qué candidatos NO cuentan como "enviados al cliente".

Una sola definición para las seis queries de Interviewed → Sent y Sent → Hired, mismo
criterio que _periods.py. Seis copias del mismo NOT EXISTS se desincronizan al primer
cambio, y estas métricas ya tienen la mitad de sus reglas escritas en comentarios.
"""
from __future__ import annotations

# El gate de client process (cv_client_process_clearances) deja a un candidato FUERA del
# envío a sales cuando está en 3+ oportunidades "En proceso con Cliente" y la supervisión
# no lo habilitó. Ese candidato nunca llegó al cliente, así que no es un "enviado".
#
# Es el mismo argumento con el que la owner sacó a 'Rejected By Sales' el 2026-08-31 ("un
# candidato que sales frenó nunca llegó al cliente"), y este llegó todavía menos lejos:
# aquél al menos pasó por sales, éste ni siquiera entró a la cola de review.
#
# POR QUÉ NO SE MIRA candidates_batches: bloquear no toca esa tabla. La fila del candidato
# queda tal cual, con status = NULL — que es justo el valor que estas métricas leen como
# "enviado al cliente, todavía sin decisión". Sin este predicado, un bloqueado cuenta como
# enviado: infla el numerador de Interviewed → Sent y el denominador de Sent → Hired.
#
# 'pending' cuenta igual que 'rejected' (decisión de la owner, 2026-09-09): mientras espera
# el OK tampoco se envió. Si después se aprueba y la recruiter reenvía el batch, la
# habilitación pasa a 'approved' y el candidato vuelve a contar solo, sin tocar nada acá.
#
# EL PAR ES (candidato, VACANTE), no sólo el candidato: la habilitación se pide de nuevo
# para cada oportunidad. La vacante sale de `b` y no de `cb` porque
# candidates_batches.opportunity_id está 100% NULL (ver opportunity_metrics_routes.py:151).
#
# Exige que la query tenga los alias `cb` (candidates_batches) y `b` (batch, o un CTE que
# exponga batch_id y opportunity_id).
CLIENT_PROCESS_NOT_BLOCKED = """NOT EXISTS (
              SELECT 1 FROM cv_client_process_clearances cpc
               WHERE cpc.candidate_id   = cb.candidate_id
                 AND cpc.opportunity_id = b.opportunity_id
                 AND cpc.status IN ('rejected', 'pending')
            )"""

# La forma "flag" para las queries que excluyen en el numerador (COUNT ... FILTER) en vez
# del WHERE: si TODOS los presentados de una opp quedaran afuera, la opp desaparecería de
# la cohorte y se llevaría sus entrevistados del denominador. Ver el comentario largo en
# interviewed_sent_30d_summary.py.
CLIENT_PROCESS_BLOCKED_FLAG = """EXISTS (
              SELECT 1 FROM cv_client_process_clearances cpc
               WHERE cpc.candidate_id   = cb.candidate_id
                 AND cpc.opportunity_id = b.opportunity_id
                 AND cpc.status IN ('rejected', 'pending')
            )"""
