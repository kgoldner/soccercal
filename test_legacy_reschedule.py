"""Missing-ID PL reschedules must not erase separate or ambiguous fixtures."""
from datetime import datetime,timedelta,timezone
from zoneinfo import ZoneInfo
from pathlib import Path
import copy,json
import soccer_cal as s
cfg=json.loads(Path(__file__).with_name('config.json').read_text());tz=ZoneInfo(cfg['timezone'])
now=datetime(2026,10,16,12,tzinfo=timezone.utc)
f=s.Fixture('eng.1','Premier League','401878769',datetime(2026,10,18,15,30,tzinfo=timezone.utc),'Nottingham Forest','Arsenal',venue='The City Ground')
def old(uid='old',day=17,categories='Premier League',title='Nottingham Forest vs Arsenal'):
 return s._build_existing(['UID:'+uid,'SUMMARY:'+title,'CATEGORIES:'+categories,
  f'DTSTART:202610{day:02d}T140000Z','DESCRIPTION:Competition: Premier League\\nSchedule note: Kickoff time is provisional and may move for UK television/competition scheduling.\\nSource: https://www.premierleague.com/en/news/4675097/fixtures\\nUser note: DVR',
  'URL:https://www.premierleague.com/en/news/4675097'],tz)
canonical=s._build_existing(s.event_lines(f,cfg,tz,'20261015T000000Z',2),tz)
def run(existing,fixtures=None):
 blocks,stats=s.merge(cfg,fixtures or [f],{e.uid:e for e in existing},set(),tz,now,False)
 return blocks,stats
blocks,stats=run([old(),canonical]);assert len(blocks)==1
assert s._prop(blocks[0],'UID')==canonical.uid
assert 'User note: DVR' in s._prop(blocks[0],'DESCRIPTION')
assert 'https://www.premierleague.com/en/news/4675097' in s._prop(blocks[0],'DESCRIPTION')
assert int(s._prop(blocks[0],'SEQUENCE'))==3
blocks,_=run([old()]);assert len(blocks)==1 and s._prop(blocks[0],'UID')=='old'
assert s._prop(blocks[0],'X-SOCCERCAL-ESPN-ID')==f.espn_id
women=old('women',categories="Women's Super League")
blocks,_=run([canonical,women]);assert len(blocks)==2
women_f=copy.deepcopy(f);women_f.comp_key='eng.w.1';women_f.comp_name="Women's Super League"
assert not s.legacy_reschedule_matches(women_f,[women_f],{'women':women})
other=copy.deepcopy(f);other.start_utc-=timedelta(days=2);other.espn_id='other'
assert not s.legacy_reschedule_matches(f,[f,other],{'old':old()})
assert not s.legacy_reschedule_matches(f,[f],{'a':old('a'),'b':old('b')})
identified=old();identified.lines.append('X-SOCCERCAL-ESPN-ID:different')
assert not s.legacy_reschedule_matches(f,[f],{'old':identified})
custom=old();custom.lines.append('X-USER:preserve')
assert not s.legacy_reschedule_matches(f,[f],{'old':custom})
reverse=old(title='Arsenal vs Nottingham Forest')
assert not s.legacy_reschedule_matches(f,[f],{'old':reverse})
far=old(day=10)
assert not s.legacy_reschedule_matches(f,[f],{'old':far})
blocks,_=run([old(),canonical,women])
parsed=[s._build_existing(b,tz) for b in blocks]
second,stats=run(parsed)
assert len(second)==2 and stats.updated==0
assert s._prop(second[0],'UID') in {canonical.uid,women.uid}
print('PASS: adjacent-day migration, canonical UID/notes/link, missing-ID-only migration, women/reverse-leg/distant/ambiguous/custom-event guards, idempotence')
