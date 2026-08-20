"""Domain errors with machine-readable codes; the API layer maps them to JSON error responses."""

from __future__ import annotations

from typing import Any


class DomainError(Exception):
    code = "domain_error"
    http_status = 409

    def __init__(self, message: str, **extra: Any):
        super().__init__(message)
        self.extra = extra


class UnknownAgent(DomainError):
    code = "unknown_agent"
    http_status = 404


class AgentGone(DomainError):
    code = "agent_gone"


class NameTaken(DomainError):
    code = "name_taken"


class InvalidRecipient(DomainError):
    code = "invalid_recipient"


class BodyTooLarge(DomainError):
    code = "body_too_large"
    http_status = 413


class TurnViolation(DomainError):
    code = "turn_violation"


class GatePendingBlock(DomainError):
    code = "gate_pending"


class NotPending(DomainError):
    code = "not_pending"


class CannotRelease(DomainError):
    code = "cannot_release"


class LineNotFound(DomainError):
    code = "line_not_found"
    http_status = 404


class MessageNotFound(DomainError):
    code = "message_not_found"
    http_status = 404


class NotAllowed(DomainError):
    code = "not_allowed"
    http_status = 403


class CannotRemoveOperator(DomainError):
    code = "cannot_remove_operator"


class InvalidToken(DomainError):
    code = "invalid_token"
    http_status = 401


class NotAttached(DomainError):
    code = "not_attached"


class InvalidEndpoint(DomainError):
    code = "invalid_endpoint"
    http_status = 400
