#!/usr/bin/env python3
"""
soccer_cal.py — daily-refreshing soccer calendar builder.

Pulls fixtures from ESPN's public (unofficial) site API, filters them to a
configured set of teams and competitions, and merges them into an existing
.ics file.

Key behaviour: matches are never added after the fact. A fixture that has
already kicked off (beyond --backfill-window-hours) is only ever *updated*
if it is already in the calendar; it is never newly inserted. Past events
already in the file are preserved untouched, so the calendar accumulates a
history rather than rewriting one.

Standard library only. Python 3.9+.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ESPN_BASE = "https://site.api.espn.com/apis/site/v2/sports/soccer"
USER_AGENT = "soccer-cal/1.0 (personal calendar builder)"
PRODID = "-//soccer_cal.py//Soccer Calendar//EN"

LOG_LEVEL = 1  # 0 quiet, 1 normal, 2 verbose


def log(msg: str, level: int = 1) -> None:
    if LOG_LEVEL >= level:
        print(msg, file=sys.stderr)


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------

def fetch_json(url: str, retries: int = 3, timeout: int = 25):
    """GET JSON with retries. Returns None on persistent failure."""
    last_err = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            last_err = f"HTTP {e.code}"
            if e.code in (400, 404):
                return None  # bad slug; no point retrying
        except Exception as e:  # noqa: BLE001
            last_err = str(e)
        if attempt < retries - 1:
            time.sleep(1.5 * (attempt + 1))
    log(f"    ! fetch failed ({last_err}): {url}", 2)
    return None


# --------------------------------------------------------------------------
# Text helpers
# --------------------------------------------------------------------------

def normalize(s: str) -> str:
    """Lowercase, strip accents and punctuation, collapse whitespace."""
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower()
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def team_matches(team_cfg: dict, *names: str) -> bool:
    """True if any ESPN name string for a competitor identifies this team."""
    pool = " | ".join(normalize(n) for n in names if n)
    if not pool:
        return False
    for bad in team_cfg.get("exclude_names", []):
        if normalize(bad) in pool:
            return False
    for good in team_cfg.get("match_names", []):
        g = normalize(good)
        if not g:
            continue
        # word-boundary match so "usa" doesn't hit "usaka"
        if re.search(rf"(^|\W){re.escape(g)}($|\W)", pool):
            return True
    return False


# --------------------------------------------------------------------------
# Fixture model
# --------------------------------------------------------------------------

@dataclass
class Fixture:
    comp_key: str
    comp_name: str
    espn_id: str
    start_utc: datetime
    home: str
    away: str
    venue: str = ""
    time_confirmed: bool = True
    broadcasts: list = field(default_factory=list)
    status: str = "CONFIRMED"

    def summary(self) -> str:
        return f"{self.home} vs {self.away}"

    def match_key(self) -> str:
        """Stable identity: competition + unordered team pair + calendar date.

        Uses the date rather than the exact time so a kickoff-time change
        updates the existing event instead of creating a duplicate.
        """
        pair = "|".join(sorted([normalize(self.home), normalize(self.away)]))
        day = self.start_utc.strftime("%Y%m%d")
        return f"{self.comp_key}|{pair}|{day}"

    def uid(self) -> str:
        h = hashlib.sha1(self.match_key().encode("utf-8")).hexdigest()[:24]
        return f"{h}@soccer-calendar.local"

    def legacy_key(self) -> str:
        """Looser identity used to recognise events from the original file,
        which used opaque UIDs. Teams + date only, no competition."""
        pair = "|".join(sorted([normalize(self.home), normalize(self.away)]))
        return f"{pair}|{self.start_utc.strftime('%Y%m%d')}"


# --------------------------------------------------------------------------
# ESPN parsing
# --------------------------------------------------------------------------

def parse_espn_event(ev: dict, comp_key: str, comp_name: str) -> "Fixture | None":
    try:
        comps = ev.get("competitions") or []
        if not comps:
            return None
        comp = comps[0]
        competitors = comp.get("competitors") or []
        if len(competitors) < 2:
            return None

        home = away = None
        for c in competitors:
            t = c.get("team") or {}
            name = (
                t.get("displayName")
                or t.get("name")
                or t.get("shortDisplayName")
                or ""
            )
            alts = [
                t.get("displayName", ""),
                t.get("shortDisplayName", ""),
                t.get("name", ""),
                t.get("abbreviation", ""),
                t.get("location", ""),
            ]
            entry = (name, alts)
            if c.get("homeAway") == "home":
                home = entry
            elif c.get("homeAway") == "away":
                away = entry
        if not home or not away:
            home, away = _fallback_sides(competitors)
            if not home or not away:
                return None

        raw_date = ev.get("date") or comp.get("date")
        if not raw_date:
            return None
        start_utc = _parse_iso_utc(raw_date)
        if start_utc is None:
            return None

        venue_obj = comp.get("venue") or {}
        addr = venue_obj.get("address") or {}
        venue_bits = [
            venue_obj.get("fullName", ""),
            addr.get("city", ""),
            addr.get("country", ""),
        ]
        venue = ", ".join(b for b in venue_bits if b)

        broadcasts = []
        for b in comp.get("broadcasts") or []:
            for n in b.get("names") or []:
                if n and n not in broadcasts:
                    broadcasts.append(n)
        for b in comp.get("geoBroadcasts") or []:
            media = (b.get("media") or {}).get("shortName")
            if media and media not in broadcasts:
                broadcasts.append(media)

        status_name = (
            ((ev.get("status") or {}).get("type") or {}).get("name")
            or ((comp.get("status") or {}).get("type") or {}).get("name")
            or ""
        )
        status = "CANCELLED" if "POSTPONED" in status_name or "CANCELED" in status_name else "CONFIRMED"

        fx = Fixture(
            comp_key=comp_key,
            comp_name=comp_name,
            espn_id=str(ev.get("id") or ""),
            start_utc=start_utc,
            home=home[0],
            away=away[0],
            venue=venue,
            time_confirmed=bool(comp.get("timeValid", True)),
            broadcasts=broadcasts,
            status=status,
        )
        fx._home_alts = home[1]  # type: ignore[attr-defined]
        fx._away_alts = away[1]  # type: ignore[attr-defined]
        return fx
    except Exception as e:  # noqa: BLE001
        log(f"    ! could not parse event: {e}", 2)
        return None


def _fallback_sides(competitors: list):
    """Some feeds omit homeAway (neutral-site finals). Take feed order."""
    out = []
    for c in competitors[:2]:
        t = c.get("team") or {}
        name = t.get("displayName") or t.get("name") or ""
        alts = [
            t.get("displayName", ""),
            t.get("shortDisplayName", ""),
            t.get("name", ""),
            t.get("abbreviation", ""),
            t.get("location", ""),
        ]
        out.append((name, alts))
    if len(out) == 2 and out[0][0] and out[1][0]:
        return out[0], out[1]
    return None, None


def _parse_iso_utc(s: str) -> "datetime | None":
    s = s.strip()
    for fmt in ("%Y-%m-%dT%H:%MZ", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S.%fZ"):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc)
    except ValueError:
        return None


# --------------------------------------------------------------------------
# Competition sweep
# --------------------------------------------------------------------------

def month_windows(start: datetime, end: datetime):
    cur = start.replace(day=1)
    while cur < end:
        nxt = (cur.replace(day=28) + timedelta(days=8)).replace(day=1)
        yield cur, min(nxt - timedelta(days=1), end)
        cur = nxt


def resolve_slug(comp: dict) -> "tuple[str, dict] | tuple[None, None]":
    """Try each candidate slug; return the first that answers, with its payload."""
    for slug in comp.get("slug_candidates", []):
        data = fetch_json(f"{ESPN_BASE}/{slug}/scoreboard?limit=1", retries=2)
        if data is not None and "leagues" in data:
            return slug, data
    return None, None


def calendar_dates(payload: dict, start: datetime, end: datetime) -> list:
    """ESPN publishes the exact dates a competition has fixtures on.

    Entries are either ISO date strings or {startDate, endDate} objects,
    depending on the competition's calendarType.
    """
    out = []
    leagues = payload.get("leagues") or []
    if not leagues:
        return out
    for entry in leagues[0].get("calendar") or []:
        if isinstance(entry, str):
            d = _parse_iso_utc(entry)
            if d:
                out.append(d)
        elif isinstance(entry, dict):
            s = _parse_iso_utc(entry.get("startDate", "") or "")
            e = _parse_iso_utc(entry.get("endDate", "") or "")
            if s and e:
                cur = s
                while cur <= e and (cur - s).days < 400:
                    out.append(cur)
                    cur += timedelta(days=1)
            elif s:
                out.append(s)
    uniq = sorted({d.strftime("%Y%m%d") for d in out if start <= d <= end})
    return uniq


def _collect(url: str, comp: dict, into: dict) -> int:
    data = fetch_json(url)
    if not data:
        return 0
    n = 0
    for ev in data.get("events") or []:
        fx = parse_espn_event(ev, comp["key"], comp["name"])
        if fx:
            into[fx.match_key()] = fx
            n += 1
    return n


def sweep_competition(comp: dict, slug: str, payload: dict,
                      start: datetime, end: datetime, budget: list) -> list:
    """Collect every fixture for a competition inside the window.

    ESPN's soccer scoreboard uses a whitelist calendar, and date-range
    queries are undocumented and not honoured by every competition. So:
    try a range request first, and if it comes back empty for a month the
    calendar says has fixtures, fall back to fetching those dates directly.
    """
    seen: dict = {}
    cal = calendar_dates(payload, start, end)

    if not cal:
        # Tournament with no published calendar: month-by-month range sweep.
        for w_start, w_end in month_windows(start, end):
            if budget[0] <= 0:
                break
            rng = f"{w_start.strftime('%Y%m%d')}-{w_end.strftime('%Y%m%d')}"
            budget[0] -= 1
            _collect(f"{ESPN_BASE}/{slug}/scoreboard?dates={rng}&limit=800", comp, seen)
            time.sleep(0.25)
        return list(seen.values())

    # Group the known fixture dates by month.
    by_month: dict = {}
    for d in cal:
        by_month.setdefault(d[:6], []).append(d)

    range_mode = None  # None = untested, True/False once decided
    for month, days in sorted(by_month.items()):
        if budget[0] <= 0:
            log("    ! request budget exhausted", 2)
            break

        if range_mode is not False:
            rng = f"{days[0]}-{days[-1]}"
            budget[0] -= 1
            before = len(seen)
            _collect(f"{ESPN_BASE}/{slug}/scoreboard?dates={rng}&limit=800", comp, seen)
            gained = len(seen) - before
            time.sleep(0.25)
            if range_mode is None:
                # Decide once: a working range query returns roughly a
                # month's worth of fixtures, not one date's worth.
                range_mode = gained > 0 and (len(days) == 1 or gained > len(days) * 0.4)
                log(f"    range queries {'work' if range_mode else 'unsupported'} "
                    f"for {slug} ({gained} from {len(days)} dates)", 2)
            if range_mode:
                continue
            # fall through and fetch this month per-date

        for day in days:
            if budget[0] <= 0:
                break
            budget[0] -= 1
            _collect(f"{ESPN_BASE}/{slug}/scoreboard?dates={day}&limit=500", comp, seen)
            time.sleep(0.25)

    return list(seen.values())


# --------------------------------------------------------------------------
# Filtering rules
# --------------------------------------------------------------------------

UCL_SHORTLIST = {"psg", "real_madrid", "barcelona", "man_city", "man_united",
                 "bayern", "arsenal", "liverpool"}
PL_CLUBS = {"man_city", "man_united", "arsenal"}


def identify_teams(fx: Fixture, teams: dict) -> set:
    ids = set()
    for side in ("_home_alts", "_away_alts"):
        alts = getattr(fx, side, [])
        for tid, cfg in teams.items():
            if cfg.get("require_womens") and not _is_womens(fx):
                continue
            if not cfg.get("require_womens") and _is_womens(fx) and tid != "uswnt":
                continue
            if team_matches(cfg, *alts):
                ids.add(tid)
    return ids


def _is_womens(fx: Fixture) -> bool:
    blob = normalize(f"{fx.comp_key} {fx.comp_name} {fx.home} {fx.away}")
    return bool(re.search(r"(^|\W)(w|women|womens|femenino|feminine|frauen)($|\W)", blob))


def keep_fixture(fx: Fixture, rule: str, teams: dict) -> bool:
    involved = identify_teams(fx, teams)
    fx._involved = involved  # type: ignore[attr-defined]

    if rule == "always":
        return True
    if rule == "ucl_shortlist":
        return bool(involved & UCL_SHORTLIST)
    if rule == "premier_league_clubs":
        return bool(involved & PL_CLUBS)
    if rule == "follow_all_teams":
        return any(teams[t].get("follow") == "all" for t in involved)
    if rule == "any_followed_team":
        return bool(involved)
    return False


# --------------------------------------------------------------------------
# ICS reading
# --------------------------------------------------------------------------

def unfold(text: str) -> list:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    out = []
    for line in text.split("\n"):
        if line[:1] in (" ", "\t") and out:
            out[-1] += line[1:]
        else:
            out.append(line)
    return [l for l in out if l != ""]


@dataclass
class ExistingEvent:
    uid: str
    lines: list
    start: "datetime | None"
    summary: str
    categories: str
    sequence: int
    dtstamp: str
    comp_key: str
    fingerprint: str


def _prop(lines: list, name: str) -> str:
    pref = name.upper()
    for l in lines:
        head = l.split(":", 1)[0].split(";", 1)[0].upper()
        if head == pref:
            return l.split(":", 1)[1] if ":" in l else ""
    return ""


def _prop_full(lines: list, name: str) -> str:
    pref = name.upper()
    for l in lines:
        head = l.split(":", 1)[0].split(";", 1)[0].upper()
        if head == pref:
            return l
    return ""


def parse_ics(path: Path, tz: ZoneInfo) -> dict:
    """Return {uid: ExistingEvent} from an existing calendar file."""
    if not path or not path.exists():
        return {}
    lines = unfold(path.read_text(encoding="utf-8"))
    events, cur, depth_tz = {}, None, False
    for l in lines:
        u = l.upper()
        if u == "BEGIN:VTIMEZONE":
            depth_tz = True
            continue
        if u == "END:VTIMEZONE":
            depth_tz = False
            continue
        if depth_tz:
            continue
        if u == "BEGIN:VEVENT":
            cur = []
            continue
        if u == "END:VEVENT":
            if cur:
                ev = _build_existing(cur, tz)
                if ev.uid:
                    events[ev.uid] = ev
            cur = None
            continue
        if cur is not None:
            cur.append(l)
    return events


def _build_existing(lines: list, tz: ZoneInfo) -> ExistingEvent:
    uid = _prop(lines, "UID")
    dtstart_line = _prop_full(lines, "DTSTART")
    start = None
    if dtstart_line and ":" in dtstart_line:
        val = dtstart_line.split(":", 1)[1].strip()
        try:
            if val.endswith("Z"):
                start = datetime.strptime(val, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
            elif "T" in val:
                start = datetime.strptime(val, "%Y%m%dT%H%M%S").replace(tzinfo=tz)
            else:
                start = datetime.strptime(val, "%Y%m%d").replace(tzinfo=tz)
        except ValueError:
            start = None
    try:
        seq = int(_prop(lines, "SEQUENCE") or 0)
    except ValueError:
        seq = 0
    cats = _prop(lines, "CATEGORIES")
    comp_key = _prop(lines, "X-SOCCERCAL-COMP")
    fp = _prop(lines, "X-SOCCERCAL-FP")
    return ExistingEvent(
        uid=uid,
        lines=lines,
        start=start,
        summary=_prop(lines, "SUMMARY"),
        categories=cats,
        sequence=seq,
        dtstamp=_prop(lines, "DTSTAMP"),
        comp_key=comp_key,
        fingerprint=fp,
    )


def existing_legacy_key(ev: ExistingEvent) -> str:
    """Team-pair + date key so events written by the original generator
    (opaque UIDs) can be recognised and replaced rather than duplicated."""
    if not ev.start:
        return ""
    s = ev.summary.replace("\\,", ",")
    parts = re.split(r"\s+vs\.?\s+|\s+v\s+", s, flags=re.I)
    if len(parts) != 2:
        return ""
    pair = "|".join(sorted([normalize(parts[0]), normalize(parts[1])]))
    return f"{pair}|{ev.start.astimezone(timezone.utc).strftime('%Y%m%d')}"


# --------------------------------------------------------------------------
# ICS writing
# --------------------------------------------------------------------------

def esc(s: str) -> str:
    return (
        s.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\n", "\\n")
    )


def fold(line: str) -> str:
    """Fold to <=75 octets per RFC 5545, never splitting a UTF-8 character.
    Continuation lines are prefixed with one space (which counts toward 75)."""
    if len(line.encode("utf-8")) <= 75:
        return line
    pieces, cur, first = [], "", True
    for ch in line:
        limit = 75 if first else 74  # 74 + leading space = 75
        if len((cur + ch).encode("utf-8")) > limit:
            pieces.append(cur)
            cur, first = ch, False
        else:
            cur += ch
    if cur:
        pieces.append(cur)
    return pieces[0] + "".join("\r\n " + p for p in pieces[1:])


VTIMEZONE_NY = """BEGIN:VTIMEZONE
TZID:America/New_York
X-LIC-LOCATION:America/New_York
BEGIN:DAYLIGHT
TZOFFSETFROM:-0500
TZOFFSETTO:-0400
TZNAME:EDT
DTSTART:19700308T020000
RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=2SU
END:DAYLIGHT
BEGIN:STANDARD
TZOFFSETFROM:-0400
TZOFFSETTO:-0500
TZNAME:EST
DTSTART:19701101T020000
RRULE:FREQ=YEARLY;BYMONTH=11;BYDAY=1SU
END:STANDARD
END:VTIMEZONE""".split("\n")


def build_description(fx: Fixture, bmap: dict) -> str:
    entry = bmap.get(fx.comp_key) or bmap.get("_default", {})
    bits = [f"Competition: {fx.comp_name}"]
    bits.append(f"U.S. streaming/broadcast: {entry.get('primary','')}")
    bits.append(f"Requested-service check: {entry.get('check','')}")
    if fx.broadcasts:
        bits.append("ESPN-listed carriers: " + ", ".join(fx.broadcasts))
    if not fx.time_confirmed:
        bits.append("Schedule note: kickoff time not yet confirmed; verify closer to the date.")
    if fx.status == "CANCELLED":
        bits.append("Schedule note: this fixture is listed as postponed or cancelled.")
    bits.append("Source: ESPN fixture feed, refreshed daily.")
    return "\n".join(bits)


def event_lines(fx: Fixture, cfg: dict, tz: ZoneInfo, dtstamp: str,
                sequence: int) -> list:
    dur = int(cfg.get("default_duration_minutes", 120))
    local_start = fx.start_utc.astimezone(tz)
    local_end = local_start + timedelta(minutes=dur)
    desc = build_description(fx, cfg.get("broadcast_map", {}))
    fp = hashlib.sha1(
        "|".join([
            fx.summary(), local_start.strftime("%Y%m%dT%H%M%S"),
            fx.venue, desc, fx.status,
        ]).encode("utf-8")
    ).hexdigest()[:12]

    lines = [
        f"UID:{fx.uid()}",
        f"DTSTAMP:{dtstamp}",
        f"SUMMARY:{esc(fx.summary())}",
        f"CATEGORIES:{esc(fx.comp_name)}",
        f"DTSTART;TZID={cfg['timezone']}:{local_start.strftime('%Y%m%dT%H%M%S')}",
        f"DTEND;TZID={cfg['timezone']}:{local_end.strftime('%Y%m%dT%H%M%S')}",
    ]
    if fx.venue:
        lines.append(f"LOCATION:{esc(fx.venue)}")
    lines.append(f"DESCRIPTION:{esc(desc)}")
    lines.append(f"STATUS:{fx.status}")
    lines.append("TRANSP:TRANSPARENT")
    if sequence:
        lines.append(f"SEQUENCE:{sequence}")
    lines.append(f"X-SOCCERCAL-COMP:{fx.comp_key}")
    lines.append(f"X-SOCCERCAL-FP:{fp}")
    return lines


def render_calendar(cfg: dict, event_blocks: list) -> str:
    out = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        f"PRODID:{PRODID}",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{esc(cfg.get('calendar_name','Soccer'))}",
        f"X-WR-TIMEZONE:{cfg['timezone']}",
        "REFRESH-INTERVAL;VALUE=DURATION:PT12H",
        "X-PUBLISHED-TTL:PT12H",
    ]
    out.extend(VTIMEZONE_NY)
    for block in event_blocks:
        out.append("BEGIN:VEVENT")
        out.extend(block)
        out.append("END:VEVENT")
    out.append("END:VCALENDAR")
    return "\r\n".join(fold(l) for l in out) + "\r\n"


# --------------------------------------------------------------------------
# Merge
# --------------------------------------------------------------------------

@dataclass
class MergeStats:
    added: int = 0
    updated: int = 0
    unchanged: int = 0
    skipped_past: int = 0
    pruned: int = 0
    preserved: int = 0
    notes: list = field(default_factory=list)


def merge(cfg: dict, fixtures: list, existing: dict, fetched_ok: set,
          tz: ZoneInfo, now: datetime, prune: bool) -> tuple:
    cutoff = now - timedelta(hours=float(cfg.get("backfill_window_hours", 3)))
    stamp = now.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    new_by_uid = {fx.uid(): fx for fx in fixtures}
    legacy_index = {}
    for fx in fixtures:
        lk = fx.legacy_key()
        if lk:
            legacy_index.setdefault(lk, fx.uid())

    existing_by_legacy = {}
    for uid, ev in existing.items():
        lk = existing_legacy_key(ev)
        if lk:
            existing_by_legacy.setdefault(lk, uid)

    stats = MergeStats()
    blocks = []  # (sort_datetime, lines)
    consumed = set()

    for fx in fixtures:
        uid = fx.uid()
        prior = existing.get(uid)
        if prior is None:
            lk = fx.legacy_key()
            prior_uid = existing_by_legacy.get(lk)
            if prior_uid and prior_uid not in new_by_uid:
                prior = existing.get(prior_uid)
                if prior:
                    consumed.add(prior_uid)
        else:
            consumed.add(uid)

        # The core rule: never insert a fixture that has already kicked off.
        if fx.start_utc < cutoff and prior is None:
            stats.skipped_past += 1
            continue

        lines = event_lines(fx, cfg, tz, stamp, 0)
        new_fp = _prop(lines, "X-SOCCERCAL-FP")

        if prior is not None and prior.fingerprint == new_fp:
            lines = event_lines(fx, cfg, tz, prior.dtstamp or stamp, prior.sequence)
            stats.unchanged += 1
        elif prior is not None:
            lines = event_lines(fx, cfg, tz, stamp, prior.sequence + 1)
            stats.updated += 1
            stats.notes.append(f"updated: {fx.summary()} ({fx.comp_name})")
        else:
            stats.added += 1
            stats.notes.append(
                f"added:   {fx.start_utc.astimezone(tz):%Y-%m-%d %H:%M} "
                f"{fx.summary()} ({fx.comp_name})"
            )
        blocks.append((fx.start_utc, lines))

    # Existing events that the refresh did not produce.
    for uid, ev in existing.items():
        if uid in consumed:
            continue
        is_future = ev.start is not None and ev.start > now
        comp_covered = ev.comp_key in fetched_ok if ev.comp_key else False
        if prune and is_future and comp_covered:
            stats.pruned += 1
            stats.notes.append(f"removed: {ev.summary} (no longer in the feed)")
            continue
        stats.preserved += 1
        blocks.append((ev.start or datetime(1970, 1, 1, tzinfo=timezone.utc), ev.lines))

    blocks.sort(key=lambda b: b[0])
    return [b[1] for b in blocks], stats


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def main() -> int:
    global LOG_LEVEL
    ap = argparse.ArgumentParser(description="Build/refresh a soccer .ics calendar.")
    ap.add_argument("--config", default="config.json")
    ap.add_argument("--calendar", default="soccer-calendar.ics",
                    help="Calendar file to read and rewrite in place.")
    ap.add_argument("--seed", default=None,
                    help="One-time: existing .ics to import history from.")
    ap.add_argument("--months-ahead", type=int, default=13)
    ap.add_argument("--days-back", type=int, default=7)
    ap.add_argument("--max-requests", type=int, default=900,
                    help="Ceiling on API calls per run, so a misbehaving "
                         "competition cannot hammer the endpoint.")
    ap.add_argument("--no-prune", action="store_true",
                    help="Never drop future events missing from the feed.")
    ap.add_argument("--allow-empty", action="store_true",
                    help="Write even if the feed returned nothing (dangerous).")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("-q", "--quiet", action="store_true")
    args = ap.parse_args()

    LOG_LEVEL = 2 if args.verbose else (0 if args.quiet else 1)

    cfg = json.loads(Path(args.config).read_text(encoding="utf-8"))
    tz = ZoneInfo(cfg["timezone"])
    now = datetime.now(timezone.utc)

    cal_path = Path(args.calendar)
    source = Path(args.seed) if args.seed else cal_path
    if not source.exists():
        log(f"WARNING: {source} does not exist. Starting from an empty "
            f"calendar — no history will be preserved.")
        log("         If you expected existing events here, stop now and "
            "check the --calendar/--seed path rather than letting this run.")
    existing = parse_ics(source, tz)
    log(f"Loaded {len(existing)} existing events from {source}")

    start = now - timedelta(days=args.days_back)
    end = now + timedelta(days=30 * args.months_ahead)
    budget = [args.max_requests]

    fixtures, fetched_ok = [], set()
    for comp in cfg["competitions"]:
        slug, payload = resolve_slug(comp)
        if not slug:
            log(f"  – {comp['name']}: no working slug, skipped")
            continue
        found = sweep_competition(comp, slug, payload, start, end, budget)
        kept = [fx for fx in found if keep_fixture(fx, comp["rule"], cfg["teams"])]
        if found:
            fetched_ok.add(comp["key"])
        log(f"  ✓ {comp['name']} [{slug}]: {len(found)} fixtures, {len(kept)} kept "
            f"(budget left {budget[0]})")
        fixtures.extend(kept)

    # De-duplicate across competitions (a match can appear in two feeds).
    dedup = {}
    for fx in fixtures:
        dedup.setdefault(fx.match_key(), fx)
    fixtures = list(dedup.values())

    if not fixtures and not args.allow_empty:
        log("ERROR: feed returned no fixtures. Leaving the calendar untouched.")
        return 2

    blocks, stats = merge(cfg, fixtures, existing, fetched_ok, tz, now,
                          prune=not args.no_prune)
    ics = render_calendar(cfg, blocks)

    log("")
    log(f"added {stats.added} · updated {stats.updated} · unchanged {stats.unchanged} "
        f"· preserved {stats.preserved} · pruned {stats.pruned} "
        f"· skipped-already-played {stats.skipped_past}")
    for n in stats.notes[:40]:
        log(f"  {n}")
    if len(stats.notes) > 40:
        log(f"  … and {len(stats.notes) - 40} more")

    if args.dry_run:
        log("(dry run — nothing written)")
        return 0

    tmp = cal_path.with_suffix(cal_path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        f.write(ics)
    tmp.replace(cal_path)
    log(f"Wrote {cal_path} ({len(blocks)} events)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
