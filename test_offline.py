#!/usr/bin/env python3
"""Offline validation of soccer_cal.py using synthetic ESPN payloads."""
import json, shutil, sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import soccer_cal as sc

TZ = ZoneInfo("America/New_York")
NOW = datetime(2026, 8, 19, 16, 0, tzinfo=timezone.utc)

# Resolve inputs relative to this file, not the shell's cwd, so the suite
# works from anywhere. Override the calendar with argv[1].
HERE = Path(__file__).resolve().parent
CALENDAR = Path(sys.argv[1]).expanduser() if len(sys.argv) > 1 else HERE / "soccer-calendar.ics"
cfg = json.loads((HERE / "config.json").read_text(encoding="utf-8"))


def ev(eid, iso, home, away, venue="Test Ground", tv=True):
    return {
        "id": eid, "date": iso,
        "competitions": [{
            "date": iso, "timeValid": tv,
            "venue": {"fullName": venue, "address": {"city": "Town", "country": "England"}},
            "competitors": [
                {"homeAway": "home", "team": {"displayName": home, "shortDisplayName": home,
                                              "name": home, "abbreviation": home[:3].upper()}},
                {"homeAway": "away", "team": {"displayName": away, "shortDisplayName": away,
                                              "name": away, "abbreviation": away[:3].upper()}},
            ],
            "broadcasts": [{"names": ["USA Network"]}],
        }],
        "status": {"type": {"name": "STATUS_SCHEDULED"}},
    }


def make_fixtures():
    """Return (fixtures, fetched_ok) as the sweep would."""
    cases = [
        # comp_key, comp_name, rule, event
        ("eng.1", "Premier League", "premier_league_clubs",
         ev("1", "2026-08-21T19:00Z", "Arsenal", "Coventry City")),          # exists (legacy UID)
        ("eng.1", "Premier League", "premier_league_clubs",
         ev("2", "2026-09-12T14:00Z", "Chelsea", "Everton")),                # no followed team -> drop
        ("uefa.champions", "UEFA Champions League", "ucl_shortlist",
         ev("3", "2026-09-16T19:00Z", "Real Madrid", "Liverpool")),          # new future -> ADD
        ("uefa.champions", "UEFA Champions League", "ucl_shortlist",
         ev("4", "2026-09-16T19:00Z", "Ajax", "Sporting CP")),               # not shortlisted -> drop
        ("fifa.friendly.w", "International Friendly (W)", "follow_all_teams",
         ev("5", "2026-10-24T23:00Z", "United States", "Canada")),           # USWNT new -> ADD
        ("fifa.friendly", "International Friendly", "follow_all_teams",
         ev("6", "2026-06-10T18:00Z", "Croatia", "Slovenia")),               # PAST, absent -> SKIP
        ("eng.1", "Premier League", "premier_league_clubs",
         ev("7", "2026-08-22T16:30Z", "Manchester City", "Tottenham Hotspur", tv=False)),
    ]
    fixtures, ok = [], set()
    for key, name, rule, raw in cases:
        fx = sc.parse_espn_event(raw, key, name)
        assert fx is not None, f"parse failed for {raw['id']}"
        ok.add(key)
        if sc.keep_fixture(fx, rule, cfg["teams"]):
            fixtures.append(fx)
    return fixtures, ok


def main():
    fails = []

    def check(label, cond, detail=""):
        print(f"  {'PASS' if cond else 'FAIL'}  {label}{'  — ' + detail if detail and not cond else ''}")
        if not cond:
            fails.append(label)

    print("\n[1] Parse the real calendar")
    src = CALENDAR
    if not src.exists():
        print(f"  ABORT  calendar not found at {src}")
        print("         Pass a path as the first argument, or run from the "
              "folder holding soccer-calendar.ics.")
        return 1
    raw_count = src.read_text(encoding="utf-8").count("BEGIN:VEVENT")
    existing = sc.parse_ics(src, TZ)
    check(f"{raw_count} events parsed", len(existing) == raw_count,
          f"got {len(existing)} of {raw_count}")
    with_start = sum(1 for e in existing.values() if e.start)
    check("all events have a parsed DTSTART", with_start == raw_count,
          f"got {with_start} of {raw_count}")
    legacy_keys = sum(1 for e in existing.values() if sc.existing_legacy_key(e))
    check("legacy team-pair keys derived", legacy_keys == raw_count,
          f"got {legacy_keys} of {raw_count}")

    print("\n[2] Filtering rules")
    fixtures, ok = make_fixtures()
    names = sorted(f.summary() for f in fixtures)
    check("Chelsea vs Everton dropped (no followed club)",
          "Chelsea vs Everton" not in names)
    check("Ajax vs Sporting CP dropped (not UCL shortlist)",
          "Ajax vs Sporting CP" not in names)
    check("Real Madrid vs Liverpool kept (UCL shortlist)",
          "Real Madrid vs Liverpool" in names)
    check("USWNT friendly kept", "United States vs Canada" in names)
    check("5 fixtures survive filtering", len(fixtures) == 5, f"got {len(fixtures)}: {names}")

    print("\n[3] Merge against the real calendar")
    blocks, stats = sc.merge(cfg, fixtures, existing, ok, TZ, NOW, prune=False)
    print(f"      added={stats.added} updated={stats.updated} unchanged={stats.unchanged} "
          f"preserved={stats.preserved} skipped_past={stats.skipped_past}")
    check("past Croatia friendly NOT back-added", stats.skipped_past == 1,
          f"skipped_past={stats.skipped_past}")
    check("3 genuinely new fixtures added", stats.added == 3, f"added={stats.added}")
    check("existing Arsenal fixture matched, not duplicated",
          stats.added + stats.updated + stats.unchanged == 4)
    total = len(blocks)
    check("no duplicate Arsenal vs Coventry", total == raw_count + 3, f"total={total}")

    print("\n[4] Round-trip the output")
    out = Path("/tmp/out.ics")
    open(out, "w", encoding="utf-8", newline="").write(sc.render_calendar(cfg, blocks))
    reparsed = sc.parse_ics(out, TZ)
    check("round-trips to same event count", len(reparsed) == total,
          f"{len(reparsed)} vs {total}")
    text = out.read_bytes().decode("utf-8")
    check("no alerts present", "BEGIN:VALARM" not in text)
    check("uses America/New_York TZID", "DTSTART;TZID=America/New_York" in text)
    longest = max(len(l.encode()) for l in text.split("\r\n"))
    check("all lines folded to <=75 octets", longest <= 75, f"longest={longest}")
    check("CRLF line endings", text.count("\r\n") > 100 and "\n\n" not in text)

    print("\n[5] Idempotence: re-run against its own output")
    blocks2, stats2 = sc.merge(cfg, fixtures, reparsed, ok, TZ, NOW + timedelta(hours=6), prune=False)
    check("second run adds nothing", stats2.added == 0, f"added={stats2.added}")
    check("second run changes nothing", stats2.updated == 0, f"updated={stats2.updated}")
    check("event count stable", len(blocks2) == total, f"{len(blocks2)} vs {total}")

    print("\n[6] A kickoff-time change updates in place")
    moved = [f for f in fixtures if f.summary() == "Real Madrid vs Liverpool"][0]
    moved.start_utc = moved.start_utc + timedelta(hours=2)
    blocks3, stats3 = sc.merge(cfg, fixtures, reparsed, ok, TZ, NOW, prune=False)
    check("time change = update, not duplicate", stats3.updated == 1 and stats3.added == 0,
          f"updated={stats3.updated} added={stats3.added}")
    check("count unchanged after reschedule", len(blocks3) == total, f"{len(blocks3)}")

    print("\n[7] Prune only touches future events in fetched competitions")
    blocks4, stats4 = sc.merge(cfg, fixtures, reparsed, {"eng.1"}, TZ, NOW, prune=True)
    past_kept = sum(1 for e in reparsed.values() if e.start and e.start <= NOW)
    check("past events never pruned", stats4.pruned < len(reparsed) - past_kept + 1)
    check("legacy events (no X-SOCCERCAL-COMP) survive prune",
          stats4.pruned == 0, f"pruned={stats4.pruned}")

    print("\n" + ("ALL CHECKS PASSED" if not fails else f"{len(fails)} FAILED: {fails}"))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
