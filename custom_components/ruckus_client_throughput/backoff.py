"""Exponential back-off with jitter and a cap (plain Python, no Home Assistant).

Used by the direct-login source so that a broken session or an unreachable controller can never cause a login
storm: after each failure the next attempt is pushed further away (30 s, 60 s, 120 s ... up to 10 minutes), with a
random spread so two things that failed together do not retry together.
"""
from __future__ import annotations

import random
import time
from collections.abc import Callable


class Backoff:
    def __init__(
        self,
        minimum: float,
        maximum: float,
        jitter: float = 0.2,
        *,
        rng: Callable[[], float] = random.random,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.minimum, self.maximum, self.jitter = float(minimum), float(maximum), float(jitter)
        self._rng, self._clock = rng, clock
        self.failures = 0
        self._until = 0.0

    def failed(self) -> float:
        """Record a failure; returns the number of seconds to wait before the next attempt."""
        delay = min(self.maximum, self.minimum * (2 ** self.failures))
        delay *= 1 + (self._rng() * 2 - 1) * self.jitter        # +- jitter
        delay = max(0.0, min(self.maximum, delay))             # the cap is a hard limit, jitter included
        self.failures += 1
        self._until = self._clock() + delay
        return delay

    def succeeded(self) -> None:
        """A good attempt: forget the failures."""
        self.failures = 0
        self._until = 0.0

    def wait_left(self) -> float:
        """Seconds still to wait (0 when an attempt is allowed now)."""
        return max(0.0, self._until - self._clock())
