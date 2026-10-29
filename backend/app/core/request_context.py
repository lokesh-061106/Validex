"""Per-request context (client IP, acting user) used by the audit ledger."""

from contextvars import ContextVar

client_ip: ContextVar[str | None] = ContextVar("client_ip", default=None)
actor_role: ContextVar[str | None] = ContextVar("actor_role", default=None)
