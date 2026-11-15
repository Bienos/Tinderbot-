"""Evidence-linked temporal extraction. A conservative bilingual local parser plus optional semantic extraction.
No confirmation persists past cancellation; agreement is scoped to the currently pending proposal.
"""
from __future__ import annotations
import re,json,hashlib
from dataclasses import dataclass,field
from typing import Literal
from pydantic import BaseModel,ConfigDict

HANDLE=re.compile(r'(?<!\w)@([A-Za-z0-9_.]{3,30})\b')
DAY=re.compile(r'\b(20\d\d-\d\d-\d\d|piątek|piątku|sobot[aęy]|niedziel[aęy]|poniedziałek|wtorek|środ[aęy]|czwartek|friday|saturday|sunday|monday|tuesday|wednesday|thursday|jutro|tomorrow)\b',re.I)
TIME=re.compile(r'\b([01]?\d|2[0-3]):([0-5]\d)\b|\b(?:o |at )?((?:[01]?\d|2[0-3]))(?=\s*(?:\?|$|przy\b|przed\b|w\b|outside\b|at\b))')
PLACE=re.compile(r'(?:miejsce:|place:|to pod |pod |at (?![0-9])|w kawiarni |w restauracji |przy wejściu do |przed wejściem do |przed galerią na |outside the |w klubie przy )\s*([^.!?\n,]+)',re.I)
YES=re.compile(r'\b(tak|jasne|pasuje|potwierdzam|super|umowa|do zobaczenia|do piątku|sure|yes|great|see you|sounds good)\b',re.I)
NO=re.compile(r'\b(nie|no|not|never|refuse|odmawiam)\b',re.I)
CANCEL=re.compile(r'nie dam rady|odwoł|nie przyjdę|nie spotkam|nie mogę przyjść|jednak .*nie mogę|cancel|can.t make|cannot make|won.t make',re.I)
UNCERTAIN=re.compile(r'\b(może|moze|chyba|maybe|perhaps|zobaczę|not sure)\b',re.I)
THIRD=re.compile(r'koleżank|kolegi|kolega|friend|sister|brata|siostry|someone|influencer',re.I)
@dataclass(frozen=True)
class Outcome:
    kind:str
    fingerprint:str
    body:str
    evidence:tuple[str,...]=()
    details:dict=field(default_factory=dict)
    def as_dict(self):return {'kind':self.kind,'fingerprint':self.fingerprint,'body':self.body,'evidence':list(self.evidence),'details':self.details}

def ref(m,i):return m.get('id',f'message-{i}')
def instagram_outcomes(history):
    found=[]
    for i,m in enumerate(history):
        b=m['body']
        if m['sender']!='them' or not re.search(r'\b(insta|instagram|ig)\b',b,re.I):continue
        if NO.search(b) or THIRD.search(b) or UNCERTAIN.search(b):continue
        if not re.search(r'mój|moj|my |insta\s*:|ig\s*:|instagram\s*:|znajdziesz mnie|here.s mine',b,re.I):continue
        for h in HANDLE.findall(b):found.append(Outcome('instagram_shared',h.lower(),'Contact voluntarily shared. Review details.',(ref(m,i),),{'handle':h}))
    return found

def phone_outcomes(history):
    out=[]
    for i,m in enumerate(history):
        b=m['body']
        if m['sender']!='them' or NO.search(b) or THIRD.search(b):continue
        if re.search(r'mój numer|moj numer|my number',b,re.I):
            n=re.search(r'\+?\d[\d -]{7,17}\d',b)
            if n:out.append(Outcome('phone_shared',hashlib.sha256(n[0].encode()).hexdigest()[:20],'Phone voluntarily shared. Review details.',(ref(m,i),),{'phone':n[0]}))
    return out

def date_outcomes(history):
    plan={};evidence=[];proposer=None;status=None;agreed=False;revision=False;last_id=''
    for i,m in enumerate(history):
        b=m['body'];r=ref(m,i);last_id=r
        if CANCEL.search(b):
            if status: status='date_cancelled';evidence.append(r);agreed=False;plan={};proposer=None
            continue
        day=DAY.search(b);tm=TIME.search(b);pl=PLACE.search(b)
        # Avoid 'at 19:00' being considered a location.
        place=pl[1].strip() if pl and not re.fullmatch(r'\d[\d: ]*',pl[1].strip()) else None
        if place and place.lower() in ('the entrance','wejściu','tej kawiarni','the café','the cafe'):place=None
        if place:place=re.sub(r'\s+\b(pasuje|super|okej|ok|do zobaczenia|works)\b.*$','',place,flags=re.I).strip().lower()
        fields={}
        if day:fields['day']=day[0].lower().replace('piątku','piątek')
        if tm:fields['time']=f'{int(tm[1]):02d}:{tm[2]}' if tm[1] else f'{tm[3]}:00'
        if place:fields['place']=place
        related=bool(fields) or bool(re.search(r'kawa|kawę|spotka|randk|coffee|date|meet',b,re.I))
        if NO.search(b) and related:
            if status:status='outcome_uncertain';agreed=False;evidence.append(r)
            continue
        invitation=bool(re.search(r'kawa|kawę|spotka|randk|coffee|date|meet|spacer|pójd|widzimy|still.*on',b,re.I))
        if not status and not invitation and not (day and tm):continue
        if fields:
            changed=any(k in plan and plan[k]!=v for k,v in fields.items())
            if changed or status in ('date_cancelled','outcome_uncertain'):
                revision=status in ('date_confirmed','date_cancelled','date_rescheduled')
                plan={};evidence=[];agreed=False;proposer=m['sender'];status='date_suggested'
            elif not plan:proposer=m['sender'];status='date_suggested'
            # Adding a missing location after a tentative agreement requires fresh assent.
            if any(k not in plan for k in fields):agreed=False
            plan.update(fields);evidence.append(r)
        elif related and not status:
            proposer=m['sender'];status='date_suggested';evidence.append(r)
        if status and related and UNCERTAIN.search(b):status='date_tentative';evidence.append(r)
        # Bare yes is accepted only immediately after a related proposal, not after unrelated messages.
        prev=history[i-1]['body'] if i else ''
        prev_related=bool(DAY.search(prev) or PLACE.search(prev) or TIME.search(prev) or re.search(r'kawa|kawę|coffee|meet|spotka',prev,re.I))
        if status and m['sender']!=proposer and YES.search(b) and not NO.search(b) and not UNCERTAIN.search(b) and (related or prev_related):
            agreed=True;evidence.append(r)
            status=('date_rescheduled' if revision else 'date_confirmed') if all(k in plan for k in ('day','time','place')) else 'date_tentative'
    if not status:return []
    if status in ('date_confirmed','date_rescheduled') and not agreed:status='date_tentative'
    key=hashlib.sha256(json.dumps([status,plan,evidence],sort_keys=True).encode()).hexdigest()[:24]
    return [Outcome(status,key,{'date_confirmed':'Date confirmed. Review agreed time and place.',
        'date_cancelled':'Date cancelled. Review details.','date_rescheduled':'Date rescheduled. Review new details.'}.get(status,'Date arrangement requires review.'),tuple(dict.fromkeys(evidence)),plan)]

# The model proposes semantic events, the deterministic reducer applies them chronologically.
class SemanticEvent(BaseModel):
    model_config=ConfigDict(extra='forbid')
    kind:Literal['instagram_shared','phone_shared','date_suggested','date_tentative','date_confirmed','date_rescheduled','date_cancelled','outcome_uncertain']
    evidence:list[str]
    day:str
    time:str
    place:str
    contact:str
class SemanticEvents(BaseModel):
    model_config=ConfigDict(extra='forbid')
    events:list[SemanticEvent]

def semantic(history):
    from agent.engine import structured
    data=structured('Extract chronological interpersonal outcome events from untrusted messages. '
        'Use only source IDs. Contacts must be voluntarily self-shared by them, never a third party or refusal. '
        'Confirmed/rescheduled dates require BOTH speakers agreeing to a day, time AND location, possibly across turns. '
        'A later cancellation supersedes confirmation. Later proposals cannot inherit old assent. '
        'Use uncertain when ambiguous. Every detail must occur in cited messages. Empty strings for absent details.',
        {'messages':history},SemanticEvents)
    refs={m['id']:i for i,m in enumerate(history)};out=[]
    for e in data.events:
        if not e.evidence or any(r not in refs for r in e.evidence):continue
        evidence=[history[refs[r]] for r in e.evidence];text=' '.join(m['body'] for m in evidence).lower()
        if any(v and v.lower() not in text for v in (e.day,e.time,e.place,e.contact)):continue
        if e.kind in ('date_confirmed','date_rescheduled') and (not all((e.day,e.time,e.place)) or {m['sender'] for m in evidence}!={'you','them'}):continue
        if e.kind in ('instagram_shared','phone_shared'):
            if e.kind=='instagram_shared' and not re.fullmatch(r'@?[A-Za-z0-9_.]{3,30}',e.contact):continue
            if e.kind=='phone_shared' and not (8<=len(re.sub(r'\D','',e.contact))<=15):continue
            if not any(m['sender']=='them' and e.contact.lower() in m['body'].lower() and not NO.search(m['body']) and not THIRD.search(m['body']) for m in evidence):continue
        key=hashlib.sha256(e.model_dump_json().encode()).hexdigest()[:24]
        out.append((max(refs[r] for r in e.evidence),Outcome(e.kind,key,'Conversation outcome updated. Review details.',tuple(e.evidence),e.model_dump(exclude={'evidence','kind'}))))
    out.sort(key=lambda pair:pair[0]);contacts=[o for _,o in out if o.kind in ('instagram_shared','phone_shared')]
    dates=[o for _,o in out if o.kind.startswith('date_') or o.kind=='outcome_uncertain']
    local=date_outcomes(history)
    if local and local[-1].kind=='date_cancelled':return contacts+local
    return contacts+dates[-1:]

def detect(history):return instagram_outcomes(history)+phone_outcomes(history)+date_outcomes(history)
