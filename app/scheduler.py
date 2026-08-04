from datetime import datetime, time
from typing import Any, Dict, List, Optional

DAY_MAP = {
    "monday": 0, "maandag": 0, "mon": 0, "ma": 0,
    "tuesday": 1, "dinsdag": 1, "tue": 1, "di": 1,
    "wednesday": 2, "woensdag": 2, "wed": 2, "wo": 2,
    "thursday": 3, "donderdag": 3, "thu": 3, "do": 3,
    "friday": 4, "vrijdag": 4, "fri": 4, "vr": 4,
    "saturday": 5, "zaterdag": 5, "sat": 5, "za": 5,
    "sunday": 6, "zondag": 6, "sun": 6, "zo": 6,
}


def parse_hhmm(value: str) -> time:
    hour, minute = value.split(":", 1)
    return time(int(hour), int(minute))


def day_matches(days: List[str], now: datetime) -> bool:
    if not days:
        return True
    wanted = []
    for d in days:
        key = str(d).strip().lower()
        if key in DAY_MAP:
            wanted.append(DAY_MAP[key])
    return now.weekday() in wanted


def time_matches(rule_time: Dict[str, str], now: datetime) -> bool:
    start = parse_hhmm(rule_time.get("start", "00:00"))
    end = parse_hhmm(rule_time.get("end", "23:59"))
    current = now.time()
    if start <= end:
        return start <= current < end
    # over midnight, e.g. 22:00-02:00
    return current >= start or current < end


def month_matches(months: Any, now: datetime) -> bool:
    if months in (None, "all", "*"):
        return True
    return int(now.month) in [int(m) for m in months]


def month_day_matches(rule: Dict[str, Any], now: datetime) -> bool:
    month_days = rule.get("month_days")
    if not month_days:
        return True
    return now.day in [int(d) for d in month_days]


def repeat_matches(rule: Dict[str, Any], now: datetime) -> bool:
    # Eerste dev-versie: daily/weekly/monthly interval=1 wordt ondersteund.
    # Niet-1 interval bewaren we alvast, maar blokkeren we nog niet hard.
    repeat = rule.get("repeat", {}) or {}
    rtype = repeat.get("type", "weekly")
    interval = int(repeat.get("interval", 1))
    if interval <= 1:
        return True
    # Simpele voorspelbare basis zonder zware calendar-library.
    if rtype == "daily":
        return (now.toordinal() % interval) == 0
    if rtype == "weekly":
        iso_week = int(now.strftime("%V"))
        return (iso_week % interval) == 0
    if rtype == "monthly":
        return (now.month % interval) == 0
    return True


def find_active_schedule(config: Dict[str, Any], now: Optional[datetime] = None) -> Optional[Dict[str, Any]]:
    now = now or datetime.now()
    active: List[Dict[str, Any]] = []
    for rule in config.get("schedule", []):
        if not rule.get("enabled", True):
            continue
        if not month_matches(rule.get("months"), now):
            continue
        if not day_matches(rule.get("days", []), now):
            continue
        if not month_day_matches(rule, now):
            continue
        if not time_matches(rule.get("time", {}), now):
            continue
        if not repeat_matches(rule, now):
            continue
        active.append(rule)
    if not active:
        return None
    active.sort(key=lambda item: int(item.get("priority", 0)), reverse=True)
    return active[0]
