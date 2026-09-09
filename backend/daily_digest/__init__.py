"""Digest diario de pendientes de carga, a un canal de Slack.

Lun a Vie 9:00 ART: un mensaje al canal mencionando a cada persona con los datos
que le faltan cargar en el Hub. Tres reglas (pricing del hire, job description,
datos base de la opp), todas RECALCULADAS desde la base cada manana.

Ese "recalculadas" es el punto y no un detalle de implementacion: a proposito NO
se reusa `utils/hr_lead_todo.py` ni la tabla `to_do`. Un to-do tiene columna
`check` y `_todo_exists` deduplica por (user_id, description, due_date) sin
mirarla, asi que una vez tildado no vuelve a aparecer aunque el campo siga
vacio. La pregunta que este modulo hace cada dia es "?el salary sigue en cero?",
no "?alguna vez avisamos de esto?".
"""
