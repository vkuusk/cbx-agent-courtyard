"""Pure unit tests for the turn-taking state machine — every transition, every illegal move."""

from uuid import uuid4

import pytest

from courtyard.hub.core import turns
from courtyard.hub.core.errors import (
    CannotRelease,
    GatePendingBlock,
    NotPending,
    TurnViolation,
)

A, B, M = uuid4(), uuid4(), uuid4()


def idle(mode="supervised"):
    return turns.TurnState(mode, "idle", None, None)


def awaiting(who, msg, mode="supervised"):
    return turns.TurnState(mode, "awaiting_reply", who, msg)


def pending(msg, mode="supervised"):
    return turns.TurnState(mode, "pending_gate", None, msg)


class TestPlanMessageSend:
    def test_idle_supervised_goes_to_gate(self):
        plan = turns.plan_message_send(idle(), A, B)
        assert plan == turns.SendPlan("pending_gate", None, "pending_gate", None, True)

    def test_idle_auto_pass_delivers_and_awaits(self):
        plan = turns.plan_message_send(idle("auto_pass"), A, B)
        assert plan == turns.SendPlan("queued", None, "awaiting_reply", B, True)

    def test_either_side_may_initiate_from_idle(self):
        plan = turns.plan_message_send(idle("auto_pass"), B, A)
        assert plan.awaiting_from == A

    def test_reply_on_supervised_line_is_gated_too(self):
        plan = turns.plan_message_send(awaiting(B, M), B, A)
        assert plan == turns.SendPlan("pending_gate", M, "pending_gate", None, True)

    def test_reply_on_auto_pass_completes_the_exchange(self):
        plan = turns.plan_message_send(awaiting(B, M, "auto_pass"), B, A)
        assert plan == turns.SendPlan("queued", M, "idle", None, False)

    def test_turn_violation_when_sender_is_not_the_addressee(self):
        with pytest.raises(TurnViolation) as exc:
            turns.plan_message_send(awaiting(B, M), A, B)
        assert exc.value.extra["awaiting_from"] == str(B)
        assert exc.value.extra["in_flight_msg"] == str(M)

    def test_nobody_may_send_while_gate_is_pending(self):
        for sender, recipient in ((A, B), (B, A)):
            with pytest.raises(GatePendingBlock):
                turns.plan_message_send(pending(M), sender, recipient)


class TestPlanGateDecision:
    def test_approve_initial_message_awaits_reply(self):
        plan = turns.plan_gate_decision(pending(M), M, None, B, "approve")
        assert plan == turns.GatePlan("queued", "awaiting_reply", B, M, False)

    def test_approve_reply_returns_line_to_idle(self):
        plan = turns.plan_gate_decision(pending(M), M, uuid4(), A, "approve")
        assert plan == turns.GatePlan("queued", "idle", None, None, False)

    def test_return_goes_back_to_sender(self):
        plan = turns.plan_gate_decision(pending(M), M, None, B, "return")
        assert plan == turns.GatePlan("returned", "idle", None, None, True)

    def test_drop_ends_the_exchange_and_notifies(self):
        plan = turns.plan_gate_decision(pending(M), M, None, B, "drop")
        assert plan == turns.GatePlan("dropped", "idle", None, None, True)

    def test_decision_on_non_pending_line_refused(self):
        with pytest.raises(NotPending):
            turns.plan_gate_decision(idle(), M, None, B, "approve")
        with pytest.raises(NotPending):
            turns.plan_gate_decision(awaiting(B, M), M, None, B, "approve")

    def test_decision_on_wrong_message_refused(self):
        with pytest.raises(NotPending):
            turns.plan_gate_decision(pending(M), uuid4(), None, B, "approve")


class TestPlanRelease:
    def test_release_a_stuck_awaiting_line(self):
        turns.plan_release(awaiting(B, M))  # no raise

    def test_release_idle_line_refused(self):
        with pytest.raises(CannotRelease):
            turns.plan_release(idle())

    def test_release_with_pending_gate_refused(self):
        with pytest.raises(CannotRelease):
            turns.plan_release(pending(M))
