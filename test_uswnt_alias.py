"""USWNT legacy alias matching stays scoped to women's exact kickoff."""
from datetime import datetime,timedelta,timezone
from zoneinfo import ZoneInfo
import soccer_cal as s
cfg={'timezone':'America/New_York','broadcast_map':{}};tz=ZoneInfo(cfg['timezone'])
now=datetime(2026,10,10,12,tzinfo=timezone.utc)
f=s.Fixture('fifa.friendly.w',"Women's International Friendly",'fixture123',now+timedelta(hours=6,minutes=30),'United States','Spain')
def existing(uid,title,start,categories,notes=''):
 return s._build_existing(['UID:'+uid,'SUMMARY:'+title,'CATEGORIES:'+categories,'DTSTART:'+start.strftime('%Y%m%dT%H%M%SZ'),'DESCRIPTION:'+notes],tz)
canonical=existing(f.uid(),f.summary(),f.start_utc,f.comp_name,'User note: DVR')
legacy=existing('legacy','USWNT vs Spain',f.start_utc,'International Friendly','Source: https://www.ussoccer.com/fixture\\nUser note: watch later')
men=existing('men','United States vs Spain',f.start_utc,'International Friendly')
later=existing('later','USWNT vs Spain',f.start_utc+timedelta(days=3),'International Friendly')
items={e.uid:e for e in [canonical,legacy,men,later]}
blocks,stats=s.merge(cfg,[f],items,set(),tz,now,False)
assert len(blocks)==3
ids={s._prop(b,'UID') for b in blocks};assert ids=={canonical.uid,'men','later'}
b=next(b for b in blocks if s._prop(b,'UID')==canonical.uid)
assert 'watch later' in s._prop(b,'DESCRIPTION') and 'DVR' in s._prop(b,'DESCRIPTION')
assert 'https://www.ussoccer.com/fixture' in s._prop(b,'DESCRIPTION')
parsed={s._build_existing(b,tz).uid:s._build_existing(b,tz) for b in blocks}
again,_=s.merge(cfg,[f],parsed,set(),tz,now,False)
assert len(again)==3
# A standalone legacy USWNT event is updated under its existing UID.
blocks,_=s.merge(cfg,[f],{'legacy':legacy},set(),tz,now,False)
assert len(blocks)==1 and s._prop(blocks[0],'UID')=='legacy'
print('PASS: USWNT alias collapses duplicate, retains UID/notes/links, preserves men and other dates, reruns stably')
