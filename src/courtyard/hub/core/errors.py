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


class NotLinked(DomainError):
    """Manual discovery (§5.8, D22): the sender has no line with that peer — the adapter
    surfaces this as the tool result, same idiom as a turn violation."""

    code = "not_linked"


class AlreadyLinked(DomainError):
    code = "already_linked"


class ThreadStillOpen(DomainError):
    """D34: a declared new ask while the line's thread is still open — refused the way
    turn violations are, instead of being silently filed into the open thread."""

    code = "thread_open"


class NoOpenThread(DomainError):
    """Close called on a line with no open thread — nothing to close."""

    code = "no_open_thread"


class ThreadLocked(DomainError):
    """D34 (§5 item 2): the send would grow a thread whose exchange budget is spent —
    the hub locked the thread (that lock is already committed and the peer told) and
    the send is refused, the way turn violations are."""

    code = "thread_locked"


class NotThreadInitiator(DomainError):
    """D34: only the agent that opened a thread may close it (the ask is theirs to
    declare satisfied)."""

    code = "not_thread_initiator"
    http_status = 403


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


class ArchiveNotFound(DomainError):
    code = "archive_not_found"
    http_status = 404


class NotAllowed(DomainError):
    code = "not_allowed"
    http_status = 403


class CannotRemoveOperator(DomainError):
    code = "cannot_remove_operator"


class InvalidToken(DomainError):
    code = "invalid_token"
    http_status = 401


class ShiftBusy(DomainError):
    """End shift refused: lines are mid-conversation (the UI confirms, then forces)."""

    code = "shift_busy"


class NoShiftToResume(DomainError):
    """Resume called with no shift open (D25 — resume exists for the stale shift)."""

    code = "no_shift"


class InvalidSetting(DomainError):
    code = "invalid_setting"
    http_status = 422


class NoStoredToken(DomainError):
    code = "no_stored_token"


class NotAttached(DomainError):
    code = "not_attached"


class InvalidEndpoint(DomainError):
    code = "invalid_endpoint"
    http_status = 400


class WorkdirNotFound(DomainError):
    code = "workdir_not_found"
    http_status = 400


class MalformedMcpJson(DomainError):
    code = "malformed_mcp_json"
    http_status = 409


class NothingToUninstall(DomainError):
    code = "nothing_to_uninstall"
    http_status = 404


class TeamNotFound(DomainError):
    code = "team_not_found"
    http_status = 404


class TeamExists(DomainError):
    """That charter directory is already registered."""

    code = "team_exists"


class ShiftActive(DomainError):
    """Reloading or selecting the current team is refused while a shift runs: projection
    changes registrations under live agents. End the shift first (D33, lean guard)."""

    code = "shift_active"


class CharterNotLoaded(DomainError):
    """Agent registration changes write back to the current team's charter (D33,
    slice 3), and a charter that did not load cannot be written into. Fix the files
    and reload the team, or clear the team selection, then retry."""

    code = "charter_not_loaded"


class CharterWriteFailed(DomainError):
    """The database change went through but writing the charter files did not; the
    message states what half-state that leaves and how to reconcile it."""

    code = "charter_write_failed"


class CharterNameRequired(DomainError):
    """The directory has no team-definition.yml; it can be initialized into a charter,
    but the team needs a name first — the WebUI catches this code and offers exactly
    that, and the name doubles as the operator's confirmation to write the file."""

    code = "charter_name_required"
    http_status = 422
