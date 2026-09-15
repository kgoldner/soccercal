#!/bin/bash
# Refresh soccer-calendar.ics from ESPN, then commit + push it only if the
# refresh succeeded AND the file actually changed.
#
# Run by launchd (com.soccercal.refresh) daily. Safe to run by hand too.
#
# Never pass public/soccer-calendar.ics as --calendar: it is a symlink to the
# top-level file, and soccer_cal.py's atomic tmp+rename would replace the
# symlink with a regular file.

set -u
REPO=/Users/kgoldner/soccercal
CAL=soccer-calendar.ics
export PATH=/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin

cd "$REPO" || { echo "cannot cd to $REPO"; exit 1; }

echo "=== $(date '+%Y-%m-%d %H:%M:%S') refresh start"
# Pick up anything pushed from elsewhere first; never rewrite local work.
git pull -q --ff-only origin main || echo "warning: could not fast-forward from origin; continuing"
if ! /usr/bin/python3 soccer_cal.py --calendar "$CAL" --verbose; then
    echo "refresh FAILED; calendar not published"
    exit 1
fi

if git diff --quiet -- "$CAL"; then
    echo "no fixture changes; nothing to publish"
    exit 0
fi

# Commit only the calendar, even if other files happen to be modified.
git add -- "$CAL"
if ! git commit -q -m "Refresh fixtures $(date +%Y-%m-%d)" -- "$CAL"; then
    echo "git commit FAILED"
    exit 1
fi
if ! git push -q origin HEAD:main; then
    echo "git push FAILED (commit is local; next run will push it)"
    exit 1
fi
echo "published $(git rev-parse --short HEAD)"
