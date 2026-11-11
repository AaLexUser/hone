"""Writes the order exports of the time zone scenario.

python3 make_files.py <project dir>

<project dir>/Inbox gets the order system's exports for October and the first half of
November. They run over whole UTC days, created_at is in UTC with a trailing Z, and
nothing in the files names the time zone. The shop counts its days in Beijing time.
The flash sale opens at midnight Beijing time on 11 November, which is 16:00 UTC on
10 November, so grouping by the UTC date makes 10 November look busier than the sale day.
"""

import csv
import random
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

BEIJING = timezone(timedelta(hours=8))
CHANNELS = [("app", 0.55), ("marketplace", 0.25), ("web", 0.12), ("social", 0.08)]

# Share of a normal day's orders in each Beijing hour.
NORMAL_HOURS = [2.0, 1.0, 0.6, 0.4, 0.3, 0.4, 0.8, 1.6, 3.0, 4.5, 5.5, 5.8,
                5.6, 5.2, 5.4, 5.6, 5.5, 5.2, 5.0, 5.6, 6.8, 7.6, 7.2, 4.6]
# Orders in each Beijing hour of 11 November. The midnight rush is the largest hour of the year.
SALE_DAY = date(2026, 11, 11)
SALE_HOURS = [7200, 3100, 1300, 600, 380, 300, 380, 650, 520, 540, 560, 580,
              560, 540, 540, 560, 580, 600, 640, 720, 900, 1100, 1000, 800]
# Orders on a normal day by weekday (Monday first), lifted around the sale.
WEEKDAY = [2080, 2060, 2120, 2170, 2300, 2540, 2490]
LIFT = {date(2026, 11, 9): 1.05, date(2026, 11, 10): 1.12, date(2026, 11, 12): 1.3}
EVENING_LIFT = {date(2026, 11, 10): 1.8}
# Each export runs over whole UTC days, as the order system writes it.
EXPORTS = [("orders_2026-10.csv", date(2026, 10, 1), date(2026, 11, 1)),
           ("orders_2026-11.csv", date(2026, 11, 1), date(2026, 11, 16))]


def hourly_counts(day, rng):
    if day == SALE_DAY:
        return [round(n * rng.uniform(0.97, 1.03)) for n in SALE_HOURS]
    weights = [w * (EVENING_LIFT.get(day, 1) if h >= 20 else 1) for h, w in enumerate(NORMAL_HOURS)]
    total = sum(weights)
    orders = WEEKDAY[day.weekday()] * LIFT.get(day, 1) * rng.uniform(0.96, 1.04)
    return [round(orders * w / total * rng.uniform(0.9, 1.1)) for w in weights]


def orders(day, rng):
    rows = []
    for hour, n in enumerate(hourly_counts(day, rng)):
        start = datetime(day.year, day.month, day.day, hour, tzinfo=BEIJING)
        for _ in range(n):
            at = start + timedelta(seconds=rng.randrange(3600))
            channel = rng.choices([c for c, _ in CHANNELS], [w for _, w in CHANNELS])[0]
            amount = round(min(4999, rng.lognormvariate(4.95 if day == SALE_DAY else 5.1, 0.6)), 2)
            rows.append((at, channel, amount))
    return rows


def main(project):
    inbox = Path(project) / "Inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    rng = random.Random(1111)
    first, last = EXPORTS[0][1] - timedelta(1), EXPORTS[-1][2]
    rows = sorted(r for d in range((last - first).days + 1) for r in orders(first + timedelta(d), rng))
    order_id = 3104217
    for name, start, end in EXPORTS:
        lo = datetime(start.year, start.month, start.day, tzinfo=timezone.utc)
        hi = datetime(end.year, end.month, end.day, tzinfo=timezone.utc)
        n = 0
        with open(inbox / name, "w", newline="") as f:
            w = csv.writer(f, lineterminator="\n")
            w.writerow(["order_id", "created_at", "channel", "amount"])
            for at, channel, amount in rows:
                if lo <= at < hi:
                    order_id += 1
                    n += 1
                    w.writerow([order_id, at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), channel, f"{amount:.2f}"])
        print(name, n)


if __name__ == "__main__":
    main(sys.argv[1])
