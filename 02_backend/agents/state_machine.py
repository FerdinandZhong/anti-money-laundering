"""Case state machine. Legal transitions only; fails fast on illegal ones."""
from enum import Enum


class CaseState(str, Enum):
    ALERT_CREATED  = "ALERT_CREATED"
    COLLECTING     = "COLLECTING"
    ANALYZING      = "ANALYZING"
    REVIEWED       = "REVIEWED"
    HUMAN_DECISION = "HUMAN_DECISION"


_ALLOWED: dict[CaseState, set] = {
    CaseState.ALERT_CREATED: {CaseState.COLLECTING},
    CaseState.COLLECTING:    {CaseState.ANALYZING},
    CaseState.ANALYZING:     {CaseState.REVIEWED},
    CaseState.REVIEWED:      {CaseState.HUMAN_DECISION},
}


def transition(current: CaseState, next_state: CaseState) -> CaseState:
    assert next_state in _ALLOWED.get(current, set()), \
        f"Illegal transition {current} → {next_state}"
    return next_state


if __name__ == "__main__":
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
