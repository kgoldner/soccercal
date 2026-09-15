import sys
p = sys.argv[1] if len(sys.argv) > 1 else 'soccer-calendar.ics'
raw = open(p, encoding='utf-8', errors='replace').read().replace('\r\n', '\n')
u = []
for l in raw.split('\n'):
    if l[:1] in (' ', '\t') and u: u[-1] += l[1:]
    else: u.append(l)
evs, cur = [], None
for l in u:
    if l.upper() == 'BEGIN:VEVENT': cur = {}
    elif l.upper() == 'END:VEVENT':
        if cur is not None: evs.append(cur)
        cur = None
    elif cur is not None and ':' in l:
        k = l.split(':', 1)[0].split(';', 1)[0].upper()
        if k in ('SUMMARY', 'DTSTART', 'CATEGORIES', 'UID'):
            cur[k] = l.split(':', 1)[1]
print("total events:", len(evs))
seen = {}
for e in evs:
    key = (e.get('SUMMARY', '?'), e.get('DTSTART', '?')[:8])
    seen.setdefault(key, []).append(e)
dups = {k: v for k, v in seen.items() if len(v) > 1}
print("same match on same date, listed twice:", len(dups))
for (s, d), group in sorted(dups.items())[:15]:
    print(f"  {d}  {s}")
    for e in group:
        print(f"       competition={e.get('CATEGORIES','?')}  uid={e.get('UID','?')[:16]}")
if not dups: print("  none - no cross-competition duplicates")
