"""Integration administration services (channel diagnostics + OAuth flows).

Transport-owning helpers that used to live in ``app/api/integrations.py``:
the Zalo channel probes and webhook-sync policy, the LLM provider probes,
and the Facebook OAuth flow orchestration. The router parses the request,
calls these, and maps the domain error to a response.
"""
