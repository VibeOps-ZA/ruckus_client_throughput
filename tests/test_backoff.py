"""Exponential back-off with jitter and a cap (backoff.py)."""
from custom_components.ruckus_client_throughput.backoff import Backoff


class FakeClock:
    now = 0.0

    def __call__(self):
        return self.now


def test_doubles_until_the_cap():
    clock = FakeClock()
    b = Backoff(30, 600, jitter=0, clock=clock)
    assert [b.failed() for _ in range(7)] == [30, 60, 120, 240, 480, 600, 600]
    assert b.failures == 7


def test_jitter_stays_inside_the_spread_and_never_passes_the_cap():
    low = Backoff(30, 600, jitter=0.2, rng=lambda: 0.0)
    high = Backoff(30, 600, jitter=0.2, rng=lambda: 1.0)
    assert low.failed() == 24.0 and high.failed() == 36.0
    for _ in range(10):
        low.failed()
        high.failed()
    assert high.failed() <= 600 and low.failed() >= 0


def test_wait_left_counts_down_and_success_resets():
    clock = FakeClock()
    b = Backoff(30, 600, jitter=0, clock=clock)
    assert b.wait_left() == 0
    b.failed()
    assert b.wait_left() == 30
    clock.now = 20
    assert b.wait_left() == 10
    clock.now = 31
    assert b.wait_left() == 0
    b.failed()
    b.failed()
    b.succeeded()
    assert b.failures == 0 and b.wait_left() == 0
    assert b.failed() == 30                      # starts from the minimum again
