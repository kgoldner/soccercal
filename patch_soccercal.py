import json, collections, shutil, sys, os
changed = []
src = 'soccer_cal.py'
if not os.path.exists(src):
    sys.exit("ERROR: run this from the folder containing soccer_cal.py")
s = open(src, encoding='utf-8').read()
if 'Replay: ' in s:
    print("  script already patched")
else:
    old = ('    bits.append(f"U.S. streaming/broadcast: {entry.get(\'primary\',\'\')}")\n'
           '    bits.append(f"Requested-service check: {entry.get(\'check\',\'\')}")')
    new = ('    bits.append(f"U.S. streaming/broadcast: {entry.get(\'primary\',\'\')}")\n'
           '    bits.append(f"Replay: {entry.get(\'replay\') or '
           'bmap.get(\'_default\', {}).get(\'replay\',\'\')}")\n'
           '    bits.append(f"Requested-service check: {entry.get(\'check\',\'\')}")')
    if old not in s:
        sys.exit("ERROR: could not find build_description() to patch.")
    shutil.copy(src, src + '.bak')
    open(src, 'w', encoding='utf-8').write(s.replace(old, new, 1))
    changed.append("soccer_cal.py now emits a Replay line")
cfgp = 'config.json'
cfg = json.load(open(cfgp, encoding='utf-8'), object_pairs_hook=collections.OrderedDict)
shutil.copy(cfgp, cfgp + '.bak')
ENG = collections.OrderedDict([("label","England"),("match_names",["england"]),
    ("exclude_names",["new england","england w","women","u21","u19"]),
    ("espn_league_hint","uefa.nations"),("follow","all")])
if 'england_m' not in cfg['teams']:
    t = collections.OrderedDict()
    for k, v in cfg['teams'].items():
        t[k] = v
        if k == 'croatia_m': t['england_m'] = ENG
    if 'england_m' not in t: t['england_m'] = ENG
    cfg['teams'] = t
    changed.append("England men's team added")
ESPN_R = ("On demand in the ESPN app after the final whistle - no recording needed. "
          "Replays typically stay up for about three to four weeks.")
PARA_R = ("On demand on Paramount+ almost immediately after the final whistle, on any "
          "plan - no recording needed. Condensed replays are posted alongside it.")
FOX_R = ("Fox's streaming app carries its soccer coverage on demand; if this one lands "
         "only on FS1/FS2 through a pay-TV package, set a DVR recording (Hulu + Live TV "
         "or similar) to rewatch it.")
VAR_R = ("Depends on which carrier picks the match up. If it lands on a streaming "
         "service you subscribe to, expect an on-demand replay; if it airs only on a "
         "linear channel, record it to rewatch.")
USSF_R = ("U.S. Soccer's rights partner usually posts a full-match replay on demand; "
          "if the match airs only on a linear TNT-family channel, record it.")
replays = {
 "eng.1": ("Peacock posts full-match replays of matches it streams or that air on NBC, "
   "usually shortly after full time. Matches carried on USA Network, CNBC or Syfy are "
   "currently absent from Peacock's replay library after the Versant spin-off - for "
   "those, record the linear broadcast (DVR via Hulu + Live TV or similar) to rewatch."),
 "esp.1": ESPN_R, "eng.fa": ESPN_R, "esp.copa_del_rey": ESPN_R, "esp.super_cup": ESPN_R,
 "uefa.champions": PARA_R, "uefa.champions_qual": PARA_R, "uefa.super_cup": PARA_R,
 "eng.league_cup": PARA_R, "uefa.nations": FOX_R, "uefa.euroq": FOX_R,
 "uefa.euro": FOX_R, "fifa.worldq.uefa": FOX_R,
 "fifa.world": ("Fox's streaming app carries every match on demand in English; Peacock "
                "carries the Telemundo Spanish-language stream on demand."),
 "fifa.wwc": ("Fox's streaming app carries matches on demand in English and Peacock "
              "carries the Telemundo feed in Spanish. No recording needed."),
 "fifa.friendly.w": USSF_R, "fifa.shebelieves": USSF_R, "generic.ussf": USSF_R,
 "fifa.w.olympics": ("Peacock keeps every Olympic football match on demand for the "
                     "duration of the Games and after - no recording needed."),
 "club.friendly": ("Preseason friendlies are often geo-limited one-offs and frequently "
                   "have no replay at all. If you care about rewatching, record it live."),
 "eng.charity": VAR_R, "fifa.friendly": VAR_R, "concacaf.w.gold": VAR_R,
 "fifa.cwc": VAR_R, "fifa.intercontinental_cup": VAR_R, "global.finalissima": VAR_R,
 "_default": ("Unknown for this competition - check the carrier's on-demand library "
              "after the match, and record the broadcast if you need to be sure."),
}
FOX_P = ("Fox Sports holds the U.S. rights; most midweek fixtures stream via Fox's "
         "sub-licensing partners, with marquee matches on FS1/FS2. Spanish-language "
         "coverage on ViX/Telemundo.")
FOX_C = ("beIN Connect: No. ESPN Unlimited: No. Hulu: No direct stream. Hulu + Live TV: "
         "Yes, via included FOX/FS1/FS2 channels. HBO Max: Occasionally for select "
         "friendlies via TNT Sports. Peacock/Telemundo: Spanish-language possible. "
         "Paramount+: No.")
bm = cfg['broadcast_map']
for k in ("uefa.nations","uefa.euroq","uefa.euro","fifa.worldq.uefa"):
    if k in bm and bm[k].get('primary') != FOX_P:
        bm[k]['primary'], bm[k]['check'] = FOX_P, FOX_C
        changed.append(k + ": US rights corrected to Fox")
added = 0
for k, entry in bm.items():
    if k in replays and not entry.get('replay'):
        entry['replay'] = replays[k]; added += 1
if added: changed.append("replay guidance added to %d competitions" % added)
missing = [k for k in bm if not bm[k].get('replay')]
json.dump(cfg, open(cfgp,'w',encoding='utf-8'), indent=2, ensure_ascii=False)
print()
for c in changed: print("  patched:", c)
if not changed: print("  nothing to do - already up to date")
if missing: print("  note: no replay text for:", ", ".join(missing))
print("\n  backups: soccer_cal.py.bak, config.json.bak")
