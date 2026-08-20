#!/usr/bin/env python3
"""Offline tests for the fixture-date sweep — the part that burned 776 of 900
requests on the first live run. No network: fetch_json is stubbed.

Each scenario asserts on request COUNT as well as fixtures found, because the
original bug was invisible in the fixture count alone.
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import soccer_cal as sc  # noqa: E402

START = datetime(2026, 8, 1, tzinfo=timezone.utc)
END = datetime(2027, 6, 30, tzinfo=timezone.utc)
COMP = {"key": "test", "name": "Test Cup"}

fails = []


def check(label, cond, detail=""):
    print(f"  {'PASS' if cond else 'FAIL'}  {label}{'  — ' + detail if detail and not cond else ''}")
    if not cond:
        fails.append(label)


def fixture_event(eid, iso, home="Arsenal", away="Chelsea"):
    return {
        "id": eid, "date": iso,
        "competitions": [{
            "date": iso, "timeValid": True,
            "venue": {"fullName": "Ground", "address": {"city": "Town", "country": "England"}},
            "competitors": [
                {"homeAway": "home", "team": {"displayName": home, "shortDisplayName": home}},
                {"homeAway": "away", "team": {"displayName": away, "shortDisplayName": away}},
            ],
        }],
    }


def payload_with_calendar(cal):
    return {"leagues": [{"calendar": cal}]}


def install_stub(responder):
    """Replace fetch_json; return the list that records every URL requested."""
    urls = []

    def fake(url, retries=3, timeout=25):
        urls.append(url)
        return responder(url)

    sc.fetch_json = fake
    sc.time.sleep = lambda *_: None  # don't actually wait 0.25s per request
    return urls


def dates_param(url):
    return url.split("dates=")[1].split("&")[0]


# ---------------------------------------------------------------------------
print("\n[1] A long {startDate,endDate} span becomes windows, not 400 days")
# This is the exact shape that made Nations League cost 328 requests.
payload = payload_with_calendar([
    {"startDate": "2026-09-01T00:00Z", "endDate": "2027-06-15T00:00Z"},
])
windows = sc.calendar_windows(payload, START, END)
check("span collapses to one window per month", len(windows) == 10, f"got {len(windows)}")
check("windows are (start,end) pairs", all(len(w) == 2 for w in windows))
span = max(
    (datetime.strptime(e, "%Y%m%d") - datetime.strptime(s, "%Y%m%d")).days
    for s, e in windows
)
check("no window longer than a month", span <= 31, f"longest {span}")
check("coverage starts at the span start", windows[0][0] == "20260901", windows[0][0])
# Widening past the published end date is the point: month granularity is
# what catches fixtures ESPN has not listed a date for yet.
check("final window widens to the month end", windows[-1][1] == "20270630",
      windows[-1][1])
check("final window still covers the published end",
      windows[-1][0] <= "20270615" <= windows[-1][1])
check("windows are contiguous, no gaps between months",
      all(datetime.strptime(windows[i + 1][0], "%Y%m%d")
          - datetime.strptime(windows[i][1], "%Y%m%d") == timedelta(days=1)
          for i in range(len(windows) - 1)))


# The Premier League regression: scattered match dates within a month must
# produce ONE whole-month window, not one narrow window per weekend cluster.
print("\n[1b] Scattered match dates widen to whole months")
pl_dates = ["2026-09-05T00:00Z", "2026-09-06T00:00Z",   # weekend
            "2026-09-12T00:00Z", "2026-09-13T00:00Z",   # next weekend
            "2026-09-22T00:00Z",                        # midweek
            "2026-10-03T00:00Z"]
pl = sc.calendar_windows(payload_with_calendar(pl_dates), START, END)
check("six scattered dates become two month windows", len(pl) == 2, f"got {len(pl)}")
check("September window spans the whole month",
      pl[0] == ("20260901", "20260930"), str(pl[0]))
check("covers a fixture on an unlisted date (2026-09-19)",
      pl[0][0] <= "20260919" <= pl[0][1])


# ---------------------------------------------------------------------------
print("\n[2] Working range queries stay cheap")
payload = payload_with_calendar([
    {"startDate": "2026-09-01T00:00Z", "endDate": "2027-06-15T00:00Z"},
])


def responder_ranges_work(url):
    d = dates_param(url)
    if "-" in d:  # range query returns the month's fixtures
        return {"events": [fixture_event(f"r{d}", "2026-09-05T19:00Z")]}
    return {"events": []}


urls = install_stub(responder_ranges_work)
budget = [900]
found = sweep_competition_result = sc.sweep_competition(
    COMP, "test.slug", payload, START, END, budget, comps_left=26)
check("all requests were ranges", all("-" in dates_param(u) for u in urls),
      f"{sum(1 for u in urls if '-' not in dates_param(u))} single-date requests")
check("cost stayed under 15 requests", len(urls) < 15, f"used {len(urls)}")
check("fixtures were collected", len(found) >= 1, f"got {len(found)}")


# ---------------------------------------------------------------------------
print("\n[3] A genuinely empty competition does NOT trigger a per-date crawl")
# Supercopa spent 174 requests to find nothing. It must now spend ~one per
# window plus a single probe.
urls = install_stub(lambda url: {"events": []})
budget = [900]
found = sc.sweep_competition(COMP, "test.slug", payload, START, END, budget,
                             comps_left=26)
single = sum(1 for u in urls if "-" not in dates_param(u))
check("found nothing, correctly", len(found) == 0, f"got {len(found)}")
check("spent well under the old 174", len(urls) < 20, f"used {len(urls)}")
check("probing is bounded, not once per window", single <= 3,
      f"{single} single-date requests")


# ---------------------------------------------------------------------------
print("\n[4] Genuinely broken range queries ARE detected and fall back")


def responder_ranges_broken(url):
    d = dates_param(url)
    if "-" in d:
        return {"events": []}          # ranges silently return nothing
    return {"events": [fixture_event(f"d{d}", "2026-09-05T19:00Z", away=f"Team{d[-2:]}")]}


urls = install_stub(responder_ranges_broken)
budget = [900]
found = sc.sweep_competition(COMP, "test.slug", payload, START, END, budget,
                             comps_left=26)
single = sum(1 for u in urls if "-" not in dates_param(u))
check("fell back to per-date fetching", single > 5, f"only {single} single-date requests")
check("fixtures recovered via fallback", len(found) > 1, f"got {len(found)}")


# ---------------------------------------------------------------------------
print("\n[5] One greedy competition cannot starve the rest")
urls = install_stub(responder_ranges_broken)  # worst case: per-date crawling
budget = [900]
sc.sweep_competition(COMP, "test.slug", payload, START, END, budget, comps_left=26)
used_first = 900 - budget[0]
fair_share = 900 // 26
check("first of 26 competitions took roughly its share",
      used_first <= max(sc.MIN_COMP_REQUESTS, fair_share) + 2,
      f"took {used_first}, share is {fair_share}")
check("budget left for the other 25", budget[0] > 800, f"left {budget[0]}")

# ...and in the realistic case (ranges working) a full 26-competition pass
# leaves most of the budget unspent.
install_stub(responder_ranges_work)
budget = [900]
for i in range(26):
    sc.sweep_competition(COMP, "test.slug", payload, START, END, budget,
                         comps_left=26 - i)
check("realistic 26-competition pass is cheap", budget[0] > 600, f"left {budget[0]}")

# Worst case (every range query broken) the budget caps the damage and the
# late competitions still get served rather than being starved by the first.
install_stub(responder_ranges_broken)
budget = [900]
served = 0
for i in range(26):
    got = sc.sweep_competition(COMP, "test.slug", payload, START, END, budget,
                               comps_left=26 - i)
    if got:
        served += 1
check("worst case still serves every competition", served == 26, f"served {served}")


# ---------------------------------------------------------------------------
print("\n[6] No published calendar falls back to month windows")
urls = install_stub(responder_ranges_work)
budget = [900]
found = sc.sweep_competition(COMP, "test.slug", {"leagues": [{}]}, START, END,
                             budget, comps_left=26)
check("still swept by month", len(urls) > 0 and len(urls) <= 14, f"used {len(urls)}")
check("all month sweeps were ranges", all("-" in dates_param(u) for u in urls))


print()
if fails:
    print(f"{len(fails)} FAILED: {fails}")
    sys.exit(1)
print("ALL SWEEP CHECKS PASSED")
