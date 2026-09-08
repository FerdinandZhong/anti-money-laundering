"""Case state machine. Legal transitions only; fails fast on illegal ones."""
from enum import Enum


class CaseState(str, Enum):
    ALERT_CREATED  = "ALERT_CREATED"
    COLLECTING     = "COLLECTING"
    VERIFYING      = "VERIFYING"
    ANALYZING      = "ANALYZING"
    REVIEWED       = "REVIEWED"
    HUMAN_DECISION = "HUMAN_DECISION"


_ALLOWED: dict[CaseState, set] = {
    # VERIFYING is optional: taken when an MCP server is configured, else
    # COLLECTING → ANALYZING directly (fail-soft to the pre-verification flow).
    CaseState.ALERT_CREATED: {CaseState.COLLECTING},
    CaseState.COLLECTING:    {CaseState.VERIFYING, CaseState.ANALYZING},
    CaseState.VERIFYING:     {CaseState.ANALYZING},
    CaseState.ANALYZING:     {CaseState.REVIEWED},
    CaseState.REVIEWED:      {CaseState.HUMAN_DECISION},
}


def transition(current: CaseState, next_state: CaseState) -> CaseState:
    assert next_state in _ALLOWED.get(current, set()), \
        f"Illegal transition {current} → {next_state}"
    return next_state


if __name__ == "__main__":
    # optional VERIFYING path
    v = transition(transition(CaseState.ALERT_CREATED, CaseState.COLLECTING), CaseState.VERIFYING)
    assert transition(v, CaseState.ANALYZING) == CaseState.ANALYZING
    # direct (fail-soft) path
    s = CaseState.ALERT_CREATED
    s = transition(s, CaseState.COLLECTING)
    s = transition(s, CaseState.ANALYZING)
    s = transition(s, CaseState.REVIEWED)
    try:
        transition(s, CaseState.COLLECTING)
        assert False, "should have raised"
    except AssertionError as e:
        assert "Illegal" in str(e)
    print("state_machine: OK")
