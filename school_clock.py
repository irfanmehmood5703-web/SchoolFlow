"""School-facing calendar dates are Pakistan dates; audit instants remain UTC."""
from datetime import datetime
from zoneinfo import ZoneInfo

SCHOOL_TIMEZONE=ZoneInfo('Asia/Karachi')

def school_today():
    return datetime.now(SCHOOL_TIMEZONE).date()
