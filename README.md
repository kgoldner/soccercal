# Self-refreshing soccer calendar

Rebuilds `soccer-calendar.ics` every day from ESPN's public fixture feed and
merges the result into the existing file. Fantastical subscribes to it and picks
up changes on its own.

**The rule that matters:** a match that has already kicked off is never added.
New fixtures are only inserted while they are still in the future, so the
calendar fills forward as draws are made and never back-fills history you didn't
have. Past events already in the file are left untouched.

## What it tracks

| Scope | Rule |
| --- | --- |
| Croatia (men) | every match — friendlies, Nations League, qualifiers, tournaments |
| USWNT | every match — friendlies, SheBelieves, W Gold Cup, World Cup, Olympics |
| Real Madrid | every match — LaLiga, Copa del Rey, Supercopa, UCL, Club World Cup, club friendlies |
| Man City / Man United / Arsenal | Premier League, FA Cup, Carabao Cup, Community Shield |
| PSG, Real Madrid, Barcelona, Man City, Man United, Bayern, Arsenal, Liverpool | Champions League only |
| UEFA Super Cup | always |
| Domestic super cups | when a tracked club is involved |

Each event carries the competition, U.S. streaming availability, and a
per-service verdict for beIN Connect, ESPN Unlimited, Hulu / Hulu + Live TV,
HBO Max, Peacock/Telemundo, and Paramount+. Times are `America/New_York`.
No alarms are ever written.

## What's in this folder

```
soccer-calendar.ics                    your calendar — the live file
soccer_cal.py                          the updater
config.json                            teams, competitions, broadcast notes
test_offline.py                        22 merge checks, no network needed
test_sweep.py                          20 fixture-sweep checks, no network needed
.github/workflows/update-calendar.yml  the daily GitHub Action
com.soccercal.refresh.plist            the daily launchd job (macOS alternative)
```

You need **either** the GitHub Action **or** the launchd job, not both. Pick one
below.

---

## Option A — GitHub Actions (recommended)

Runs on GitHub's servers whether or not your Mac is on, and gives Fantastical an
HTTPS URL, which it refreshes far more reliably than a local file.

The repo has to be **public** for the calendar URL to work without an auth
token. That means the fixture list is world-readable. It's football fixtures, so
low stakes, but it is public.

This folder is already a git repo with everything committed. From
`~/Documents/calendar`:

```bash
# 1. Create the repo on GitHub (or create it in the web UI and skip to step 2)
gh repo create soccer-calendar --public --source=. --remote=origin --push

# 2. If you made it in the web UI instead:
git remote add origin https://github.com/<you>/soccer-calendar.git
git branch -M main
git push -u origin main
```

Then:

3. Open the repo's **Actions** tab → *Refresh soccer calendar* → **Run
   workflow**. Watch it once. The log prints, per competition, which slug
   resolved and how many fixtures came back. **Read that output** — see
   *First run* below.
4. Subscribe in Fantastical: File → New Calendar Subscription →

   ```
   https://raw.githubusercontent.com/<you>/soccer-calendar/main/soccer-calendar.ics
   ```

   Set auto-refresh to daily or hourly. The file advertises a 12-hour TTL.

The Action runs at 07:15 UTC daily and only commits when fixtures actually
changed, so the history stays readable.

---

## Option B — local Mac, via launchd

Nothing leaves your machine, but it only runs when the Mac is awake. The plist
already has the correct paths filled in for this folder.

```bash
cp ~/Documents/calendar/com.soccercal.refresh.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.soccercal.refresh.plist

# force one run right now to confirm it works
launchctl start com.soccercal.refresh
cat ~/Library/Logs/soccercal.err
```

It runs at 07:15 local time. If the Mac is asleep then, launchd runs it once on
the next wake rather than skipping the day. Logs land in
`~/Library/Logs/soccercal.log` and `.err` — check those first if the calendar
ever goes stale.

Fantastical can subscribe to a local file, but its refresh behaviour is less
dependable than a URL. If you go this route, consider putting the `.ics` in
iCloud Drive and subscribing to its share link.

To stop it: `launchctl unload ~/Library/LaunchAgents/com.soccercal.refresh.plist`

---

## First run

Whichever option you pick, do a dry run first — it writes nothing:

```bash
cd ~/Documents/calendar
python3 soccer_cal.py --dry-run --verbose
```

Verbose mode prints one line per competition: which slug resolved, how many
fixtures came back, how many survived filtering. **Check those lines.** If a
competition reports `no working slug` or 0 fixtures, ESPN has renamed it — edit
that competition's `slug_candidates` in `config.json`. That is the single most
likely maintenance task this will ever need.

You do **not** need `--seed`. That flag is for importing history from a
different file; your existing calendar is already at the path the script reads
and rewrites.

The first live run (20 Aug 2026) added 9 fixtures and brought the calendar to
164 events: 5 Premier League, 2 Supercopa de España, and 2 USWNT friendlies
against Spain. It costs about 310 requests of the 900 budget.

Champions League still returns 0 — the 2026-27 draw hasn't been made yet. That
is expected, and the daily run will fill it in on its own once ESPN publishes
the fixtures, because new matches are added while they are still in the
future.

## Options

| Flag | Effect |
| --- | --- |
| `--dry-run` | report changes, write nothing |
| `--seed FILE` | one-time import of history from another `.ics` |
| `--no-prune` | never remove future events that vanished from the feed |
| `--months-ahead N` | how far forward to look (default 13) |
| `--max-requests N` | ceiling on API calls per run (default 900) |
| `-v` | per-competition detail |

## Safety behaviour

- If the feed returns **nothing at all** (ESPN down, network dead), the script
  exits non-zero and leaves your calendar untouched rather than emptying it.
- If the calendar file is missing entirely, it says so loudly before building
  from scratch, so a wrong `--calendar` path can't quietly discard your history.
- Events are only pruned if they are in the future *and* belong to a competition
  that fetched successfully this run. A failed competition can't delete anything.
- Events keep a stable `UID` derived from competition + teams + date, so a
  kickoff-time change **moves** the existing event instead of duplicating it.
  Your original 155 events use opaque UIDs and are matched by team-pair-and-date
  instead, so they update rather than duplicate.
- `DTSTAMP` and `SEQUENCE` only advance when content actually changed, so
  Fantastical isn't churning 300 events every morning.
- Writes go to a temp file and are renamed into place, so an interrupted run
  can't leave a half-written calendar.

## Editing what's tracked

Everything lives in `config.json`. To follow another club, add it under `teams`
with `match_names` (lowercase substrings ESPN might use) and a `follow` value of
`all`, `domestic_and_ucl`, or `ucl_only`, then make sure the competitions you
care about are listed. To correct a broadcast note mid-season, edit
`broadcast_map` — the change appears on every event for that competition on the
next run.

## Tests

```bash
cd ~/Documents/calendar
python3 test_offline.py
```

```bash
python3 test_sweep.py
```

`test_offline.py` is 22 checks on the merge logic against your real calendar
file — that a past match isn't back-added, that a kickoff-time change moves an
event rather than duplicating it, that re-running changes nothing, that legacy
events survive pruning.

`test_sweep.py` is 20 checks on the fixture sweep, asserting on request *counts*
as well as fixtures found, because the sweep bug that reached production was
invisible in the fixture count alone.

Neither needs the network.

## Things the live runs taught us

Worth knowing before you change anything in `soccer_cal.py`:

**Don't set a User-Agent.** ESPN returns HTTP 403 for any User-Agent string it
doesn't recognise — including `soccer-cal/1.0`, and including a full Chrome
string. Python's own default (`Python-urllib/3.x`) is accepted, so the script
deliberately sends no User-Agent header. If every competition suddenly reports
`no working slug` and the log is full of 403s, this is why; the script now says
so in its error output.

**Query by month, not by date.** ESPN publishes a per-competition calendar of
fixture dates, but it is neither complete nor cheap to walk. Expanding a
`{startDate, endDate}` span into individual days once cost 776 of the 900
request budget across three competitions and starved every competition after
them into reporting fake zeros. Querying only the dates ESPN lists is cheap but
misses fixtures on unlisted dates — it lost 50 Premier League matches. Whole
calendar months are both cheaper and wider than either. `test_sweep.py` pins
all three behaviours.

**Watch the request counts, not just the fixture counts.** The per-competition
log line reports requests used and budget remaining. A competition reporting 0
fixtures after burning 100+ requests is a bug; 0 fixtures after ~15 is just an
empty competition.

## A caveat worth knowing

ESPN's fixture API is undocumented and unofficial. It is reliable in practice
and needs no API key, but nobody promises it won't change. The script is written
to fail safely rather than destructively.
