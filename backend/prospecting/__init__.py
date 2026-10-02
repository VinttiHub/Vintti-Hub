"""Prospecting — el CRM de los BDRs (empresas que llegan desde Clay).

Reemplaza a HubSpot para la prospección: Clay empuja cada empresa por webhook
(`POST /prospecting/clay/webhook`), los BDRs la trabajan en `docs/prospecting.html`
y los workflows que antes corría HubSpot viven en `workflows.py`.

Es un módulo aparte del CRM de clientes (`account`) a propósito: son otras empresas
(todavía no son clientes) y otro volumen.
"""
