"""Descriptive transaction patterns, without risk thresholds or crime labels."""
from collections import deque
from datetime import timedelta
from decimal import Decimal

from compliance.applicability import instant


def _peak(rows):
    """Largest count and amount in (end - 24 hours, end], within available data."""
    queue, total = deque(), Decimal(0)
    peak_count, peak_amount = 0, Decimal(0)
    count_end = amount_end = None
    for time, amount, _ in rows:
        while queue and queue[0][0] <= time - timedelta(hours=24):
            total -= queue.popleft()[1]
        queue.append((time, amount))
        total += amount
        if len(queue) > peak_count:
            peak_count, count_end = len(queue), time.isoformat()
        if total > peak_amount:
            peak_amount, amount_end = total, time.isoformat()
    return {'transaction_count': peak_count, 'count_window_end': count_end,
            'amount': str(peak_amount), 'amount_window_end': amount_end}


def transaction_patterns(window, account_id, activity):
    result = {'available': False, 'source': 'operational_transactions',
              'definition': 'Account-relative directions; self-transfers excluded. Other internal transfers included. '
                            'Currency-separated rolling windows use (end - 24 hours, end] within the available 30-day window. '
                            'Receipts followed by payments describe timing only, not tracing the same money. '
                            'Recipients use account IDs, otherwise recorded names; names do not establish identity.'}
    if not activity['query_complete']:
        return {**result, 'reason': 'Transaction query or amounts are incomplete.'}
    rows = {r['transaction_id']: r for r in window.get('rows', [])}
    timed = []
    try:
        for row in rows.values():
            if account_id not in (row.get('from_account_id'), row.get('to_account_id')):
                raise ValueError('Unrelated account record')
            timed.append((instant(row['event_time']), Decimal(str(row['amount'])), row))
    except (ValueError, TypeError, KeyError, OverflowError):
        return {**result, 'reason': 'Transaction timing or account attribution is incomplete.'}
    timed.sort(key=lambda item: item[0])
    currencies = {}
    for currency in sorted({r['currency'] for _, _, r in timed}):
        outgoing, incoming, recipients = [], [], {}
        unknown = 0
        self_count = 0
        for time, amount, row in timed:
            if row['currency'] != currency:
                continue
            if row.get('from_account_id') == account_id == row.get('to_account_id'):
                self_count += 1
                continue
            if row.get('from_account_id') == account_id:
                outgoing.append((time, amount, row))
                recipient = row.get('to_account_id') or row.get('counterparty_name')
                if recipient:
                    recipients[recipient] = recipients.get(recipient, Decimal(0)) + amount
                else:
                    unknown += 1
            else:
                incoming.append((time, amount, row))
        outbound = sum((a for _, a, _ in outgoing), Decimal(0))
        inbound = sum((a for _, a, _ in incoming), Decimal(0))
        # Two-pointer scan; strictly earlier receipts only. No double-use allocation is implied.
        index, latest = 0, None
        followed, followed_amount = 0, Decimal(0)
        for time, amount, _ in outgoing:
            while index < len(incoming) and incoming[index][0] < time:
                latest = incoming[index][0]
                index += 1
            if latest is not None and time - latest <= timedelta(hours=1):
                followed += 1
                followed_amount += amount
        top = max(recipients, key=recipients.get) if recipients else None
        currencies[currency] = {
            'incoming_count': len(incoming), 'outgoing_count': len(outgoing),
            'inbound_amount': str(inbound), 'outbound_amount': str(outbound),
            'self_transfer_count': self_count,
            'peak_incoming_24h': _peak(incoming), 'peak_outgoing_24h': _peak(outgoing),
            'distinct_recorded_recipients': len(recipients), 'unknown_recipient_count': unknown,
            'top_recipient': top, 'top_recipient_amount': str(recipients[top]) if top else None,
            'top_recipient_outflow_share': str(recipients[top] / outbound) if top and outbound else None,
            'payments_within_60m_after_receipt': followed,
            'payment_amount_within_60m_after_receipt': str(followed_amount),
        }
    return {**result, 'available': True, 'by_currency': currencies}


def pattern_observation(patterns):
    if not patterns['available']:
        return patterns['reason']
    parts = []
    for currency, p in patterns['by_currency'].items():
        parts.append(f"{currency}: {p['incoming_count']} incoming and {p['outgoing_count']} outgoing transactions; "
                     f"peak 24-hour incoming count {p['peak_incoming_24h']['transaction_count']}, "
                     f"outgoing count {p['peak_outgoing_24h']['transaction_count']}; "
                     f"peak 24-hour outgoing amount {p['peak_outgoing_24h']['amount']}; "
                     f"{p['distinct_recorded_recipients']} recorded recipients; "
                     f"{p['payments_within_60m_after_receipt']} payments within 60 minutes after a receipt.")
    return ' '.join(parts) or 'No transactions in the available account window.'
