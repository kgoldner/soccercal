"""Regression checks for stable ESPN identity and positive descriptions."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import soccer_cal as s
cfg={'timezone':'America/New_York','broadcast_map':{'_default':{'primary':'Assignment unknown.','check':'HBO Max: No. Paramount+: Yes.'}}}
tz=ZoneInfo(cfg['timezone']);now=datetime(2026,10,10,tzinfo=timezone.utc)
f=s.Fixture('eng.1','Premier League','123',now+timedelta(days=2),'Liverpool','Manchester City')
e=s._build_existing(s.event_lines(f,cfg,tz,'20261010T000000Z',0)+['URL:https://www.liverpoolfc.com/'],tz)
e.lines=[l+'\\nUser note: watch with family' if l.startswith('DESCRIPTION:') else l for l in e.lines]
original_uid=e.uid
for step in range(2):
 f.start_utc+=timedelta(days=1)
 blocks,stats=s.merge(cfg,[f],{e.uid:e},{'eng.1'},tz,now,False)
 assert len(blocks)==1 and stats.updated==1
 e=s._build_existing(blocks[0],tz)
 assert e.uid==original_uid
 assert s._prop(e.lines,'URL')=='https://www.liverpoolfc.com/'
 assert s._prop(e.lines,'DESCRIPTION').count('User note: watch with family')==1
 assert 'Requested-service check' not in s._prop(e.lines,'DESCRIPTION')
print('PASS: repeated date changes retain UID, notes and links; service-check row omitted')
