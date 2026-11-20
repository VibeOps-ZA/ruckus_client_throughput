"""Rate and daily-total maths (tracker.py): reset, jitter, midnight, sleep/reconnect, idle, restore."""
from custom_components.ruckus_client_throughput.tracker import IDLE_AFTER_SECONDS, ClientTracker

MAC = "aa:bb:cc:00:00:01"
DAY = "2026-11-20"
NEXT_DAY = "2026-11-21"


def counters(rx, tx, mac=MAC):
    return {mac: {"rx": rx, "tx": tx, "hostname": "tv", "ap_name": "AP", "ssid": "Home"}}


# ------------------------------------------------------------------------------------------------- rate
def test_first_sight_is_only_a_baseline():
    t = ClientTracker()
    row = t.update(counters(5_000_000, 9_000_000), 1000.0, DAY)[MAC]
    assert row["upload_kbps"] is None and row["download_kbps"] is None
    assert row["day_mb"] == 0.0                      # the counter holds history from before: not counted today
    assert row["hostname"] == "tv" and row["ssid"] == "Home"


def test_rate_is_worked_out_between_counter_changes():
    t = ClientTracker()
    t.update(counters(0, 0), 1000.0, DAY)
    row = t.update(counters(750_000, 1_500_000), 1060.0, DAY)[MAC]      # 60 s later
    assert row["upload_kbps"] == 100.0               # 750 000 B * 8 / 1000 / 60 s
    assert row["download_kbps"] == 200.0
    assert row["counter_age"] == 0


def test_rate_is_held_while_counters_do_not_move_then_drops_to_zero_when_idle():
    t = ClientTracker()
    t.update(counters(0, 0), 1000.0, DAY)
    t.update(counters(750_000, 750_000), 1060.0, DAY)
    held = t.update(counters(750_000, 750_000), 1120.0, DAY)[MAC]       # one poll without change: still held
    assert held["upload_kbps"] == 100.0 and held["counter_age"] == 60
    idle = t.update(counters(750_000, 750_000), 1060.0 + IDLE_AFTER_SECONDS + 1, DAY)[MAC]
    assert idle["upload_kbps"] == 0.0 and idle["download_kbps"] == 0.0


def test_idle_threshold_follows_a_slower_poll():
    t = ClientTracker(idle_after=300)
    t.update(counters(0, 0), 1000.0, DAY)
    t.update(counters(1000, 1000), 1100.0, DAY)
    assert t.update(counters(1000, 1000), 1350.0, DAY)[MAC]["upload_kbps"] != 0.0   # 250 s < 300 s
    assert t.update(counters(1000, 1000), 1401.0, DAY)[MAC]["upload_kbps"] == 0.0


def test_counter_reset_clears_the_rate_and_starts_again():
    t = ClientTracker()
    t.update(counters(1_000_000, 1_000_000), 1000.0, DAY)
    t.update(counters(2_000_000, 2_000_000), 1060.0, DAY)
    row = t.update(counters(500, 800), 1120.0, DAY)[MAC]          # the client re-associated
    assert row["upload_kbps"] is None and row["download_kbps"] is None
    row = t.update(counters(60_500, 60_800), 1180.0, DAY)[MAC]    # 60 000 B up, 60 000 B down in 60 s
    assert row["upload_kbps"] == 8.0 and row["download_kbps"] == 8.0


def test_the_same_reading_twice_is_not_counted_twice():
    """The gateway answers from its cache when asked again: same fetched_at, same numbers."""
    t = ClientTracker()
    t.update(counters(0, 0), 1000.0, DAY)
    first = t.update(counters(1_000_000, 0), 1060.0, DAY)[MAC]
    again = t.update(counters(1_000_000, 0), 1060.0, DAY)[MAC]
    assert first["day_mb"] == again["day_mb"] == 1.0
    older = t.update(counters(1_000_000, 0), 1050.0, DAY)[MAC]    # an older timestamp is ignored too
    assert older["day_mb"] == 1.0


# ------------------------------------------------------------------------------------------------- daily total
def test_daily_total_adds_every_positive_step_and_counts_a_reset_from_zero():
    t = ClientTracker()
    t.update(counters(100, 100), 1000.0, DAY)
    t.update(counters(2_000_100, 3_000_100), 1060.0, DAY)         # +2 MB up, +3 MB down
    assert t.day_mb(MAC, DAY) == 5.0
    t.update(counters(500_000, 500_000), 1120.0, DAY)             # counters went back: 1 MB since the reset
    assert t.day_mb(MAC, DAY) == 6.0


def test_client_that_leaves_and_returns_keeps_todays_total():
    t = ClientTracker()
    t.update(counters(0, 0), 1000.0, DAY)
    t.update(counters(1_000_000, 1_000_000), 1060.0, DAY)
    assert t.day_mb(MAC, DAY) == 2.0
    gone = t.update({}, 1120.0, DAY)
    assert gone == {} and t.day_mb(MAC, DAY) == 2.0               # the TV went to sleep: nothing lost
    row = t.update(counters(300_000, 200_000), 1180.0, DAY)[MAC]  # back; counters restarted from ~0
    assert row["day_mb"] == 2.5 and row["upload_kbps"] is None


def test_new_day_starts_at_zero_with_the_first_reading():
    t = ClientTracker()
    t.update(counters(0, 0), 1000.0, DAY)
    t.update(counters(4_000_000, 0), 1060.0, DAY)
    row = t.update(counters(4_500_000, 0), 1120.0, NEXT_DAY)[MAC]
    assert row["day"] == NEXT_DAY and row["day_mb"] == 0.5        # only the step since the last reading
    assert t.day_mb(MAC, DAY) == 0.0                              # yesterday's total is not today's


def test_midnight_roll_zeroes_everything_at_once():
    t = ClientTracker()
    t.update(counters(0, 0), 1000.0, DAY)
    rows = t.update(counters(2_000_000, 0), 1060.0, DAY)
    assert rows[MAC]["day_mb"] == 2.0
    t.roll_day(NEXT_DAY)
    assert rows[MAC]["day"] == NEXT_DAY and rows[MAC]["day_mb"] == 0.0
    nxt = t.update(counters(2_300_000, 0), 1120.0, NEXT_DAY)[MAC]  # traffic after midnight counts for the new day
    assert nxt["day_mb"] == 0.3


# ------------------------------------------------------------------------------------------------- restore
def test_restore_puts_back_the_total_after_a_restart():
    t = ClientTracker()
    t.restore_day(MAC, DAY, 7_500_000)
    row = t.update(counters(10, 10), 1000.0, DAY)[MAC]            # first reading after the restart: baseline only
    assert row["day_mb"] == 7.5
    row = t.update(counters(1_000_010, 10), 1060.0, DAY)[MAC]
    assert row["day_mb"] == 8.5


def test_restore_never_lowers_a_total_and_ignores_an_older_day():
    t = ClientTracker()
    t.update(counters(0, 0), 1000.0, DAY)
    t.update(counters(5_000_000, 0), 1060.0, DAY)
    t.restore_day(MAC, DAY, 1_000_000)                            # remembered value is older/lower: keep ours
    assert t.day_mb(MAC, DAY) == 5.0
    t.restore_day(MAC, "2026-11-19", 9_000_000)                   # yesterday's number must not come back
    assert t.day_mb(MAC, DAY) == 5.0
    t.restore_day(MAC, DAY, 6_000_000)
    assert t.day_mb(MAC, DAY) == 6.0


def test_restored_total_from_yesterday_does_not_show_today():
    t = ClientTracker()
    t.restore_day(MAC, "2026-11-19", 9_000_000)                   # HA was down over midnight
    row = t.update(counters(0, 0), 1000.0, DAY)[MAC]
    assert row["day_mb"] == 0.0 and row["day"] == DAY


def test_totals_survive_a_new_tracker_when_the_days_store_is_shared():
    """A reload of the integration (options change) builds a new tracker around the same store."""
    store: dict = {}
    first = ClientTracker(days=store)
    first.update(counters(0, 0), 1000.0, DAY)
    first.update(counters(3_000_000, 0), 1060.0, DAY)
    second = ClientTracker(days=store)
    assert second.update(counters(3_000_000, 0), 1120.0, DAY)[MAC]["day_mb"] == 3.0
