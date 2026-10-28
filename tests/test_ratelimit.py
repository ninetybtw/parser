import pytest

from leadgen.ratelimit import BudgetExceeded, RateLimiter


class FakeClock:
    def __init__(self):
        self.t = 0.0
        self.sleeps = []

    def clock(self):
        return self.t

    def sleep(self, s):
        self.sleeps.append(s)
        self.t += s


def test_enforces_min_interval():
    fc = FakeClock()
    rl = RateLimiter(min_interval=1.0, clock=fc.clock, sleep=fc.sleep)
    rl.wait()
    fc.t += 0.3
    rl.wait()
    assert fc.sleeps == [pytest.approx(0.7)]


def test_budget_stops_source():
    fc = FakeClock()
    rl = RateLimiter(min_interval=0, max_requests=2, clock=fc.clock, sleep=fc.sleep)
    rl.wait()
    rl.wait()
    with pytest.raises(BudgetExceeded):
        rl.wait()
