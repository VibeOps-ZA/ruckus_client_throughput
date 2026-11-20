"""Rate and daily-total maths (plain Python, no Home Assistant, so it can be tested on its own).

Input: the byte counters of the chosen clients and the time those counters were read.
Output, per client: upload/download rate (kbit/s), how old the counter reading is, and the data used today.

How the numbers are worked out
- The access points refresh each client's counters only about once a minute. A rate is therefore worked out
  between two *changes* of the counters, not between two polls, and held until the next change. If the counters
  have not moved for `idle_after` seconds the client really is idle and the rate drops to 0.
- The daily total adds up every positive counter step. When the counters go backwards (the client re-associated,
  the AP restarted) the new value counts as the traffic since the reset. A client that leaves the Wi-Fi and comes
  back keeps today's total; the counters restart from ~0 when it returns, so its whole new reading counts.
- The day is the local date handed in by the caller; the first reading of a new day starts that day at 0.
"""
from __future__ import annotations

IDLE_AFTER_SECONDS = 150  # counters unchanged for this long = idle (the coordinator raises it for slow polling)


class ClientTracker:
    def __init__(self, idle_after: float = IDLE_AFTER_SECONDS, days: dict | None = None) -> None:
        self.idle_after = idle_after
        # mac -> {"day": "YYYY-MM-DD", "bytes": int}. Passed in so it can outlive a reload of the integration.
        self.days: dict[str, dict] = days if days is not None else {}
        self._rate: dict[str, dict] = {}     # mac -> ts, rx, tx (at the last change), up, down (kbit/s)
        self._last: dict[str, tuple[int, int]] = {}   # mac -> counters at the previous reading (daily total)
        self._left: set[str] = set()         # clients seen before that are off the Wi-Fi now
        self._sample_ts: float | None = None
        self._rows: dict[str, dict] = {}

    # ------------------------------------------------------------------------------------------- readings
    def update(self, counters: dict[str, dict], ts: float, today: str) -> dict[str, dict]:
        """counters: {mac: {"rx": int, "tx": int, **extra}} read at `ts` (epoch seconds). Returns one row per client.

        A reading with the same (or an older) `ts` as the last one is the same data again (the gateway answers from
        its cache): nothing is counted twice and the previous rows are returned."""
        if self._sample_ts is not None and ts <= self._sample_ts and set(counters) == set(self._rows):
            return self._rows
        self._sample_ts = ts

        for mac in list(self._last):               # clients that left the Wi-Fi: forget the counter baseline only
            if mac not in counters:
                self._last.pop(mac, None)
                self._rate.pop(mac, None)
                self._left.add(mac)

        rows: dict[str, dict] = {}
        for mac, c in counters.items():
            rx, tx = int(c["rx"]), int(c["tx"])
            day = self._day(mac, today)
            base = self._last.get(mac)
            if base is None:
                if mac in self._left:              # back after leaving: the counters restarted, all of it is new
                    day["bytes"] += rx + tx
                    self._left.discard(mac)
                # else first sight since start: only a baseline (the counter holds history from before)
            else:
                d_rx, d_tx = rx - base[0], tx - base[1]
                day["bytes"] += (rx if d_rx < 0 else d_rx) + (tx if d_tx < 0 else d_tx)
            self._last[mac] = (rx, tx)

            t = self._rate.get(mac)
            if t is None:
                t = self._rate[mac] = {"ts": ts, "rx": rx, "tx": tx, "up": None, "down": None}
            elif rx < t["rx"] or tx < t["tx"]:
                t.update(ts=ts, rx=rx, tx=tx, up=None, down=None)      # counters reset: start again
            elif rx != t["rx"] or tx != t["tx"]:
                dt = max(ts - t["ts"], 1.0)
                t.update(
                    up=round((rx - t["rx"]) * 8 / 1000 / dt, 1),
                    down=round((tx - t["tx"]) * 8 / 1000 / dt, 1),
                    ts=ts, rx=rx, tx=tx,
                )
            elif ts - t["ts"] > self.idle_after:
                t.update(up=0.0, down=0.0)

            rows[mac] = {
                **c,
                "upload_kbps": t["up"],
                "download_kbps": t["down"],
                "counter_age": round(max(0.0, ts - t["ts"])),   # seconds since the counters last moved
                "day": day["day"],
                "day_mb": self.day_mb(mac, today),
            }
        self._rows = rows
        return rows

    # ------------------------------------------------------------------------------------------- daily totals
    def _day(self, mac: str, today: str) -> dict:
        d = self.days.get(mac)
        if d is None or d["day"] != today:
            d = self.days[mac] = {"day": today, "bytes": 0}
        return d

    def day_mb(self, mac: str, today: str) -> float:
        d = self.days.get(mac)
        return round(d["bytes"] / 1_000_000, 1) if d and d["day"] == today else 0.0

    def roll_day(self, today: str) -> None:
        """Local midnight: every client starts the new day at 0 (the next reading is counted into it)."""
        for mac in list(self.days):
            if self.days[mac]["day"] != today:
                self.days[mac] = {"day": today, "bytes": 0}
        for row in self._rows.values():
            row["day"], row["day_mb"] = today, 0.0

    def restore_day(self, mac: str, day: str, nbytes: int) -> None:
        """Put back the total a sensor remembers from before a restart. Never lowers what is already counted and
        never brings back an older day over a newer one."""
        cur = self.days.get(mac)
        if cur is None or cur["day"] < day:
            self.days[mac] = {"day": day, "bytes": max(0, int(nbytes))}
        elif cur["day"] == day:
            cur["bytes"] = max(cur["bytes"], int(nbytes))
        row = self._rows.get(mac)
        if row is not None:
            row["day"] = self.days[mac]["day"]
            row["day_mb"] = round(self.days[mac]["bytes"] / 1_000_000, 1)
