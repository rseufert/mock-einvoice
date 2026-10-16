"""The mock's clock: one that can be pinned, and moved forward.

    from mockeinvoice.clock import Clock

    clock = Clock("2026-10-07T09:00")       # pinned; or Clock() for real time
    clock.now()                             # an aware datetime, in UTC
    clock.advance(seconds=90)               # or to="2026-10-08T08:00"
    clock.stamp()                           # "2026-10-07T09:01:30Z"

**A pinned clock stands still.** It is at the moment it was pinned to until it
is advanced, and then at that moment, so that what a run writes does not
change from run to run: two responses given without an advance between them
carry the same second. mock-sap's pinned clock ticks on from where it was
pinned; this one does not, because a second that depends on how fast the run
went is what pinning is there to take away.

**A clock that is not pinned is real time, plus whatever it was advanced by.**

**It is UTC, and only UTC.** A time given with no zone is taken to be UTC; one
given with an offset is that moment, and is said back in UTC. Every stamp ends
in `Z`. Nothing here depends on a zone: there is no cutoff hour and no
business day.

**It does not go backwards**, because what was stamped since would then be in
the future, and one advance moves it at most about ten years.
"""
from __future__ import annotations

import datetime
import re
import threading
from typing import Callable, Dict, Optional, Union

UTC = datetime.timezone.utc
MOST = 3650 * 86400         # seconds, the furthest one advance moves
MOMENT = re.compile(r"\d{4}-\d{2}-\d{2}"
                    r"(T([01]\d|2[0-3]):[0-5]\d(:[0-5]\d)?(Z|[+-]([01]\d|2[0-3]):[0-5]\d)?)?")


class Invalid(ValueError):
    """A time the clock was not given in a way it takes, or cannot move to."""


def utc(moment: datetime.datetime) -> datetime.datetime:
    """A moment in UTC. One with no zone is taken to be UTC already."""
    if moment.tzinfo is None:
        return moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC)


def stamp(moment: datetime.datetime) -> str:
    """A moment as the mock writes one: to the second, in UTC, with a `Z`."""
    return utc(moment).replace(microsecond=0, tzinfo=None).isoformat() + "Z"


def moment(text: str) -> datetime.datetime:
    """A moment from `2026-10-07`, `2026-10-07T09:00` or `2026-10-07T09:00:30`,
    with `Z` or an offset (`+02:00`) after a time, or `Invalid`. With no zone
    it is UTC; a date alone is its midnight."""
    if not isinstance(text, str) or not MOMENT.fullmatch(text):
        raise Invalid("a time is written 2026-10-07, 2026-10-07T09:00 or "
                      "2026-10-07T09:00:30, in UTC or with Z or an offset such as +02:00 "
                      "after it, and not %r" % (text,))
    try:
        return utc(datetime.datetime.fromisoformat(text[:-1] if text.endswith("Z") else text))
    except (ValueError, OverflowError):
        raise Invalid("%s is no date and time there is" % text) from None


class Clock:
    """The time the mock goes by. Called, it is `now()`, so it can be given
    wherever a `now` is taken."""

    def __init__(self, pinned: Union[None, str, datetime.datetime] = None,
                 real: Optional[Callable[[], datetime.datetime]] = None):
        if isinstance(pinned, str):
            pinned = moment(pinned)
        self.pinned = utc(pinned) if pinned is not None else None
        self.real = real or (lambda: datetime.datetime.now(UTC))
        self.moved = datetime.timedelta(0)
        self.lock = threading.Lock()

    def now(self) -> datetime.datetime:
        return (self.pinned if self.pinned is not None else utc(self.real())) + self.moved

    __call__ = now

    def stamp(self) -> str:
        return stamp(self.now())

    def advance(self, seconds: object = None, to: object = None) -> Dict[str, object]:
        """Move the clock forward by a whole number of seconds, or to a time
        (`moment`), and say where it went, or raise `Invalid`. A time it is
        already at moves it nowhere and is no error."""
        if (seconds is None) == (to is None):
            raise Invalid("advance takes seconds, or a time to move to, and one of them")
        with self.lock:
            before = self.now()
            if seconds is not None:
                if isinstance(seconds, str) and seconds.isdigit() and seconds.isascii():
                    seconds = int(seconds)
                if isinstance(seconds, bool) or not isinstance(seconds, int) or seconds < 0:
                    raise Invalid("seconds is a whole number, nought or more, and not %r: "
                                  "a stamp is to the second" % (seconds,))
                by = seconds
            else:
                target = moment(to) if not isinstance(to, datetime.datetime) else utc(to)
                # To the second, as a stamp is: a time the clock is at within
                # the second is not behind it.
                by = int((target - before.replace(microsecond=0)).total_seconds())
                if by < 0:
                    raise Invalid("the clock does not go backwards: it is %s, and %s is "
                                  "before that" % (stamp(before), stamp(target)))
            if by > MOST:
                raise Invalid("an advance moves the clock at most %d seconds (%d days), "
                              "and this is %d" % (MOST, MOST // 86400, by))
            self.moved += datetime.timedelta(seconds=by)
            return {"from": stamp(before), "to": self.stamp(), "seconds": by,
                    "pinned": self.pinned is not None}
