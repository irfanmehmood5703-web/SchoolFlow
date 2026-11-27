"""Monthly staff totals supplement dated attendance without inventing dates.

A saved total is inclusive of the dated records, not an extra number. A change
to the underlying attendance, joining date or working calendar requires review
before payroll uses the month again.
"""
import hashlib
import json
from collections import Counter
from datetime import date
from payroll_calendar import month_dates

KIND = 'staff-monthly-attendance'
STATUSES = ('Present', 'Absent', 'Late', 'Leave', 'Short Leave', 'Off Day', 'Death Leave', 'Paper Leave')
DEDUCTIONS = ('Absent', 'Late', 'Leave', 'Short Leave', 'Death Leave', 'Paper Leave')


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def summaries(Workflow, month, employee_ids):
    if not employee_ids:
        return {}
    rows = Workflow.query.filter_by(kind=KIND, status='Active').filter(
        Workflow.data['month'].as_string() == month,
        Workflow.data['employee_id'].as_integer().in_(employee_ids)
    ).order_by(Workflow.id).all()
    result = {}
    for row in rows:
        eid = int(row.data['employee_id'])
        if eid in result:
            raise ValueError('Duplicate monthly attendance totals. Contact the school administrator.')
        result[eid] = row
    return result


def basis(month, joining, today, working_dates, rows):
    dates = month_dates(month)
    try:
        joined = date.fromisoformat(joining or '')
    except (ValueError, TypeError):
        joined = None
    elapsed = [d for d in dates if joined and joined <= d <= today]
    work = set(working_dates) if working_dates is not None else None
    eligible = {d for d in elapsed if work is None or d.isoformat() in work}
    dated = sorted((r for r in rows if r.day in elapsed), key=lambda r: r.day)
    counts = Counter(r.status for r in dated if r.day in eligible)
    lect = sum(r.lectures or 0 for r in dated)
    revision = fingerprint(dict(joining=joining or '', working_dates=sorted(work) if work is not None else None,
                                daily=[[str(r.day), r.status, r.lectures or 0] for r in dated]))
    return dict(counts=dict(counts), lectures=lect, marked=len(dated), maximum=len(eligible),
                elapsed=len(elapsed), first=elapsed[0] if elapsed else None,
                revision=revision, valid=bool(joined and elapsed))


def token(saved, base):
    return fingerprint([saved.id if saved else None, saved.data if saved else None, base['revision']])


def validate_totals(counts, lectures, base):
    if not base['valid']:
        raise ValueError('Choose a month on or after the employee joining date, with elapsed days.')
    if set(counts) != set(STATUSES) or any(type(v) is not int or not 0 <= v <= 31 for v in counts.values()):
        raise ValueError('Monthly attendance counts must be whole numbers from 0 to 31.')
    if any(counts[s] < base['counts'].get(s, 0) for s in STATUSES):
        raise ValueError('Monthly totals cannot be less than saved day-wise counts. Correct dated attendance in Day-wise attendance first.')
    historical = sum(n for s, n in base['counts'].items() if s not in STATUSES)
    if sum(counts.values()) + historical > base['maximum']:
        raise ValueError('Monthly attendance totals exceed eligible elapsed working/calendar days.')
    if type(lectures) is not int or not base['lectures'] <= lectures <= 31000:
        raise ValueError('Total lectures must be a whole number, at least the saved daily lecture total, and no more than 31,000.')


def payroll_totals(saved, base):
    if saved.data.get('revision') != base['revision']:
        raise ValueError('Monthly attendance needs review because dated records, joining date or working calendar changed. Open Monthly Attendance and save the reviewed totals.')
    counts = saved.data['counts']
    lectures = saved.data['lectures']
    validate_totals(counts, lectures, base)
    return Counter({**base['counts'], **counts}), lectures
