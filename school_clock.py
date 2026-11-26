"""School-facing calendar dates are Pakistan dates; audit instants remain UTC."""
import re
from datetime import datetime
from zoneinfo import ZoneInfo

SCHOOL_TIMEZONE=ZoneInfo('Asia/Karachi')

def school_today():
    return datetime.now(SCHOOL_TIMEZONE).date()


def normalize_clock(value):
    # Accept legacy HH:MM or explicit 12-hour AM/PM; store canonical HH:MM.
    value=(value or '').strip()
    if not value:return ''
    if re.fullmatch(r'(?:[01][0-9]|2[0-3]):[0-5][0-9]',value):return value
    match=re.fullmatch(r'(0?[1-9]|1[0-2]):([0-5][0-9])\s*([AP]M)',value,re.I)
    if not match:raise ValueError('Enter valid times in hh:mm AM/PM format.')
    hour,minute,period=match.groups()
    return f'{int(hour)%12+(12 if period.upper()=="PM" else 0):02d}:{minute}'


def attendance_clock(value):
    # Human-facing attendance clock; do not change stored or comparison values.
    if not value:return ''
    try:canonical=normalize_clock(value)
    except ValueError:return value
    if not canonical:return ''
    hour,minute=map(int,canonical.split(':'))
    return f'{hour%12 or 12:02d}:{minute:02d} {"AM" if hour<12 else "PM"}'
