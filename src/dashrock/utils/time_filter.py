"""Time filter — session windows and blackout enforcement."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time as dtime
from zoneinfo import ZoneInfo

from dashrock.config import TimeFilterCfg

_WEEKDAY_CODES = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]


@dataclass(frozen=True)
class BlackoutDecision:
    allow_new_entries: bool
    force_close: bool


def _parse_hhmm(s: str) -> dtime:
    h, m = s.split(":")
    return dtime(int(h), int(m))


def _parse_dt(s: str, tz: ZoneInfo) -> datetime:
    return datetime.strptime(s, "%Y-%m-%d %H:%M").replace(tzinfo=tz)


def evaluate(cfg: TimeFilterCfg, now: datetime) -> BlackoutDecision:
    if not cfg.enabled:
        return BlackoutDecision(allow_new_entries=True, force_close=False)

    tz = ZoneInfo(cfg.timezone)
    local_now = now.astimezone(tz)

    code = _WEEKDAY_CODES[local_now.weekday()]
    if code in {c.upper() for c in cfg.weekdays_off}:
        return BlackoutDecision(allow_new_entries=False, force_close=False)

    if cfg.sessions:
        t = local_now.time()
        inside = any(_parse_hhmm(s.start) <= t <= _parse_hhmm(s.end) for s in cfg.sessions)
        if not inside:
            return BlackoutDecision(allow_new_entries=False, force_close=False)

    for b in cfg.blackouts:
        start = _parse_dt(b.start, tz)
        end = _parse_dt(b.end, tz)
        if start <= local_now <= end:
            return BlackoutDecision(
                allow_new_entries=False,
                force_close=(b.behavior == "close_on_entry"),
            )

    return BlackoutDecision(allow_new_entries=True, force_close=False)
