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
soccer-calendar.ics                    your calendar — 155 events, the live file
soccer_cal.py                          the updater
config.json                            teams, competitions, broadcast notes
test_offline.py                        22 checks, no network needed
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

Expect the first real run to *add* a fair amount: the current file has no
Champions League matches (the draw hadn't been made when it was generated), no
USWNT matches, and no domestic super cups.

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

22 checks covering the merge logic against your real calendar file — that a past
match isn't back-added, that a kickoff-time change moves an event rather than
duplicating it, that re-running changes nothing, that legacy events survive
pruning. No network required.

## A caveat worth knowing

ESPN's fixture API is undocumented and unofficial. It is reliable in practice
and needs no API key, but nobody promises it won't change. The script is written
to fail safely rather than destructively.

The live fetch path has never been exercised against a real ESPN response — the
sandbox this was built in couldn't reach ESPN. The merge logic is well tested;
the fetching is not. That's why the dry run in *First run* matters.
