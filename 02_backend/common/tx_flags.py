"""Pure, presentation-layer transaction typology flags. No I/O. Derived from a
row's own fields (+ the case's tx set for repeat detection). These are honest
heuristics for the demo — NOT model output."""

_STRUCTURING_THRESHOLD = 50_000.0
_NEAR_BAND = 5_000.0  # within $5k below the threshold


def derive_tx_flags(tx: dict, all_txs: list[dict]) -> list[dict]:
    flags: list[dict] = []
    amount = float(tx.get("amount") or 0.0)
    if _STRUCTURING_THRESHOLD - _NEAR_BAND <= amount < _STRUCTURING_THRESHOLD:
        flags.append({"key": "near_threshold", "label": "Near-threshold",
                      "why": f"${amount:,.0f} sits just under the ${_STRUCTURING_THRESHOLD:,.0f} reporting line."})

    hour = _hour(tx.get("event_time"))
    if hour is not None and 0 <= hour <= 6:
        flags.append({"key": "off_hours", "label": "Off-hours",
                      "why": f"Executed at {hour:02d}:00 — outside normal business hours."})

    country = (tx.get("counterparty_country") or "").upper()
    if country and country != "SG":
        flags.append({"key": "cross_border", "label": "Cross-border",
                      "why": f"Counterparty in {country}, not SG."})

    name = tx.get("counterparty_name")
    if name:
        same = sum(1 for t in all_txs if t.get("counterparty_name") == name)
        if same > 1:
            flags.append({"key": "repeat_counterparty", "label": "Repeat counterparty",
                          "why": f"Same counterparty appears {same}× in this case."})
    return flags


def _hour(event_time) -> int | None:
    if not event_time or "T" not in str(event_time):
        return None
    try:
        return int(str(event_time).split("T")[1][:2])
    except (ValueError, IndexError):
        return None
