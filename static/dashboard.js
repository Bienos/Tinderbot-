
let data=null, selected=null, filter='all';
const statuses={not_synced:'Jeszcze nie sprawdzono',new_match:'Nowy match',needs_reply:'Odpowiedź oczekuje',waiting:'Czekasz na odpowiedź',paused:'Wstrzymana',archived:'Archiwum',unavailable_unknown:'Dostęp niepewny',needs_review:'Do sprawdzenia'};
function el(tag,cls,text){let x=document.createElement(tag);if(cls)x.className=cls;if(text!==undefined)x.textContent=String(text);return x}
async function api(path,method='GET',payload){let res=await fetch(path,{method,headers:{'Content-Type':'application/json','X-Agent-Request':'dashboard'},body:payload?JSON.stringify(payload):undefined});let body=await res.json().catch(()=>({}));if(!res.ok)throw Object.assign(Error(body.detail||res.status),{status:res.status});return body}

function safeImg(u){try{let x=new URL(u);return x.protocol==='https:'&&(x.hostname==='gotinder.com'||x.hostname.endsWith('.gotinder.com'))?x.href:null}catch(e){return null}}
const IMG_CACHE=new Map();
function cachedImg(key,url,cls,alt){let i=IMG_CACHE.get(key);if(!i||i.dataset.src!==url){i=el('img',cls);i.src=url;i.dataset.src=url;i.decoding='async';i.referrerPolicy='no-referrer';IMG_CACHE.set(key,i)}i.className=cls;i.alt=alt||'';return i}
function avatarFor(t,place='list'){let u=safeImg(t.profile?.photos?.[0]);if(u){let i=cachedImg(place+':'+t.id,u,'avatar',t.display_name);i.style.objectFit='cover';return i}return el('span','avatar',(t.display_name||'?').slice(0,1).toUpperCase())}
const PHOTO_IDX=new Map(),DRAFT_EDITS=new Map();
const ERR_PL={'New message invalidates draft':'Przyszła nowa wiadomość, więc ten szkic jest nieaktualny. Za chwilę powstanie nowy.','Conversation content changed; regenerate draft':'Rozmowa się zmieniła. Kliknij „Napisz inaczej”.','Profile or writing preferences changed; regenerate draft':'Zmieniłeś ustawienia stylu. Kliknij „Napisz inaczej”.','Coordinator busy':'Bot jest zajęty inną wysyłką. Spróbuj za chwilę.','Permission revoked or conversation paused':'Rozmowa albo agent jest wstrzymany.','Earlier delivery uncertain; reconcile before sending more':'Poprzednia wysyłka nie jest potwierdzona. Sprawdź rozmowę w Tinderze.','Draft already resolved or unavailable':'Ten szkic jest już wysłany albo odrzucony.'};
const IG_RE=/(?:^|[\s(])(?:ig|insta(?:gram)?)\s*[:\-–]?\s*@?([a-z0-9._]{2,30})/i;
function emptyCard(text){return el('div','rempty',text)}
function renderProfile(t){let box=document.getElementById('profile');box.replaceChildren();let p=t?.profile;
if(!t){box.append(emptyCard('Wybierz rozmowę, żeby zobaczyć profil.'));return}
if(!p||(!p.photos?.length&&!p.bio&&!p.age)){box.append(emptyCard('Brak danych profilu. Kliknij Synchronizuj po połączeniu z Tinderem.'));return}
let photos=(p.photos||[]).map(safeImg).filter(Boolean);let full=(p.photos_full||[]).map(safeImg);let big=photos.map((u,k)=>full[k]||u);
let n=photos.length,idx=Math.min(PHOTO_IDX.get(t.id)||0,Math.max(0,n-1));
const go=k=>{PHOTO_IDX.set(t.id,(k+n)%n);renderProfile(t)};
let who=el('div','pover');let nm=el('b','',t.display_name);if(p.age)nm.append(el('span','',' '+p.age));who.append(nm);
if(p.matched_at)who.append(el('small','','Dopasowanie '+fmtDate(p.matched_at)));
if(n){let stage=el('div','pstage');stage.title='Kliknij, żeby obejrzeć zdjęcia w pełnym rozmiarze';
 stage.append(cachedImg('pmain:'+t.id+':'+idx,photos[idx],'pmain',t.display_name+', zdjęcie '+(idx+1)+' z '+n));
 if(n>1){let segs=el('div','psegs');for(let k=0;k<n;k++)segs.append(el('span',k===idx?'on':''));stage.append(segs);
  for(let [cls,lab,d] of [['prev','Poprzednie zdjęcie',-1],['next','Następne zdjęcie',1]]){let b=el('button','pnav '+cls,d<0?'‹':'›');b.setAttribute('aria-label',lab);b.onclick=e=>{e.stopPropagation();go(idx+d)};stage.append(b)}}
 let zoom=el('button','pzoom');zoom.setAttribute('aria-label','Otwórz zdjęcia w pełnym rozmiarze');zoom.innerHTML='<svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true"><path fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" d="M14 4h6v6M10 20H4v-6M20 4l-7 7M4 20l7-7"/></svg>';
 stage.append(zoom,who);stage.onclick=()=>openViewer(big,idx,t.display_name+(p.age?', '+p.age:''));box.append(stage);
 if(n>1){let strip=el('div','pthumbs');photos.forEach((u,k)=>{let th=cachedImg('pthumb:'+t.id+':'+k,u,'pthumb'+(k===idx?' on':''),'');th.onclick=()=>go(k);strip.append(th)});box.append(strip)}}
else{who.className='pover flat';box.append(who)}
let info=el('div','pinfo');if(p.bio){info.append(el('p','pbio',p.bio));let ig=p.bio.match(IG_RE);if(ig){let a=el('a','igchip','Instagram @'+ig[1]);a.href='https://www.instagram.com/'+encodeURIComponent(ig[1])+'/';a.target='_blank';a.rel='noopener noreferrer';info.append(a)}}
else info.append(el('p','pbio muted','Brak opisu.'));
let meta=el('div','pmeta');if(n)meta.append(el('span','',n+(n===1?' zdjęcie':n<5?' zdjęcia':' zdjęć')));if(p.last_activity)meta.append(el('span','','Aktywność '+fmtDate(p.last_activity)));if(meta.children.length)info.append(meta);
box.append(info)}
const NEG_SIG=/nie zadaje|krócej|ponad dobę|ponad dobie/;
function renderPlan(t){let pb=document.getElementById('plan');pb.replaceChildren();if(!t){pb.append(emptyCard('Wybierz rozmowę.'));return}
if(!t.plan){pb.append(emptyCard('Brak danych.'));return}let p=t.plan;
let tone=p.move==='invite'||p.move==='settle_details'?'hot':p.stage==='fading'||p.stage==='cooldown'||p.stage==='closed'?'cold':'';
let head=el('div','plhead'),txt=el('div','');txt.append(el('span','stchip '+tone,p.stage_label),el('div','pmove',p.move_label));
let ring=el('div','ring '+(p.interest>=60?'good':p.interest<35?'low':''));ring.style.setProperty('--v',p.interest);ring.setAttribute('role','img');ring.setAttribute('aria-label','Zainteresowanie '+p.interest+' na 100');
let rv=el('span','rv');rv.append(el('b','',p.interest),el('small','','zaint.'));ring.append(rv);head.append(txt,ring);pb.append(head,el('p','pwhy',p.why));
if(p.signals?.length){let sg=el('div','sigs');for(let x of p.signals)sg.append(el('span','sigc'+(NEG_SIG.test(x)?' neg':''),x));pb.append(sg)}}
const V={list:[],i:0,name:'',zoom:false};
function vEl(id){return document.getElementById(id)}
function openViewer(list,i,name){if(!list.length)return;V.list=list;V.name=name;showV(i);let d=vEl('viewer');if(!d.open)d.showModal()}
function vZoom(on,e){V.zoom=on;let img=vEl('vimg');img.classList.toggle('zoomed',on);if(on&&e)vPan(e);else img.style.transformOrigin='50% 50%'}
function vPan(e){let r=vEl('vstage').getBoundingClientRect(),pt=e.touches?e.touches[0]:e;let x=Math.max(0,Math.min(100,(pt.clientX-r.left)/r.width*100)),y=Math.max(0,Math.min(100,(pt.clientY-r.top)/r.height*100));vEl('vimg').style.transformOrigin=x+'% '+y+'%'}
function showV(i){let n=V.list.length;V.i=(i+n)%n;vZoom(false);let img=vEl('vimg');img.referrerPolicy='no-referrer';img.src=V.list[V.i];img.alt=V.name+', zdjęcie '+(V.i+1)+' z '+n;
 vEl('vcount').textContent=(V.i+1)+' / '+n;vEl('vname').textContent=V.name;vEl('vprev').hidden=vEl('vnext').hidden=n<2;
 let th=vEl('vthumbs');th.replaceChildren();if(n>1)V.list.forEach((u,k)=>{let m=el('img',k===V.i?'on':'');m.referrerPolicy='no-referrer';m.src=u;m.alt='Zdjęcie '+(k+1);m.onclick=()=>showV(k);th.append(m)});
 for(let d of [1,-1]){let pre=new Image();pre.referrerPolicy='no-referrer';pre.src=V.list[(V.i+d+n)%n]}}
(function bindViewer(){let d=vEl('viewer');if(!d)return;let img=vEl('vimg'),stage=vEl('vstage'),sx=null,moved=false;
 vEl('vclose').onclick=()=>d.close();vEl('vprev').onclick=()=>showV(V.i-1);vEl('vnext').onclick=()=>showV(V.i+1);
 img.onclick=e=>{if(!moved)vZoom(!V.zoom,e)};stage.addEventListener('mousemove',e=>{if(V.zoom)vPan(e)});
 stage.addEventListener('click',e=>{if(e.target===stage)d.close()});d.addEventListener('click',e=>{if(e.target===d)d.close()});
 d.addEventListener('keydown',e=>{if(e.key==='ArrowLeft'){e.preventDefault();showV(V.i-1)}else if(e.key==='ArrowRight'){e.preventDefault();showV(V.i+1)}});
 stage.addEventListener('touchstart',e=>{sx=e.touches[0].clientX;moved=false},{passive:true});
 stage.addEventListener('touchmove',e=>{if(V.zoom){vPan(e);moved=true;e.preventDefault()}else if(sx!==null&&Math.abs(e.touches[0].clientX-sx)>12)moved=true},{passive:false});
 stage.addEventListener('touchend',e=>{if(!V.zoom&&sx!==null){let dx=e.changedTouches[0].clientX-sx;if(Math.abs(dx)>50)showV(V.i+(dx<0?1:-1))}sx=null;setTimeout(()=>{moved=false},50)});
 d.addEventListener('close',()=>vZoom(false))})();
function fmtDate(v){let d=new Date(v);return isNaN(d)?'':d.toLocaleDateString('pl-PL')}
function planChip(p){let c=el('span','pchip '+(p.move==='invite'||p.move==='settle_details'?'hot':p.stage==='fading'||p.stage==='cooldown'?'cold':''),p.stage_label);c.title=p.move_label+' · zainteresowanie '+p.interest+'/100';return c}
function tsOf(t){return Date.parse(t.sort_at)||0}
function matchedOf(t){return Date.parse(t.matched_at)||tsOf(t)}
function choose(id){selected=id;render()}
function threadById(){return data?.threads.find(t=>t.id===selected)}
function isConv(t){return (t.message_count||0)>0}
function filtered(t){if(!isConv(t))return false;if(filter==='all')return t.state!=='archived';if(filter==='needs')return t.state==='needs_reply';if(filter==='waiting')return t.state==='waiting';if(filter==='other')return ['archived','paused','unavailable_unknown','needs_review'].includes(t.state);return true}
function render(){if(!data)return;renderOnboarding();renderRoster();if(view==='stats')renderStats();
const notices={rate_limited:'Tinder requested a cooldown.',server_retry_after:'Tinder requested a service cooldown.',local_request_budget:'The configured Tinder traffic budget is reached.',restriction_requires_manual_review:'Tinder needs an account check in the official app.',repeated_rate_limits_requires_review:'Repeated throttling: review the account before reconnecting.',circuit_open_requires_review:'Repeated connection failures: review the account before reconnecting.',session_expired_or_account_changed:'The Tinder session expired or account identity changed.',inbox_access_denied:'Tinder denied inbox access (HTTP 401). Check your current session in Tinder and reconnect; profile access alone is insufficient.'};
let alerts=data.tinder.connections.filter(c=>c.error);let alert=document.getElementById('account-alert');alert.hidden=!alerts.length;alert.textContent=alerts.map(c=>(notices[c.error]||'Tinder connection needs attention.')+(c.enabled&&c.blocked_until>Date.now()/1000?' Next possible request: '+new Date(c.blocked_until*1000).toLocaleString():!c.enabled?' Automatic requests are stopped.':'')).join(' ');

const filters=[['all','Wszystkie'],['needs','Do odpowiedzi'],['waiting','Czekają'],['other','Pozostałe']];let fs=document.getElementById('filters');fs.replaceChildren();for(let [value,label] of filters){let b=el('button',value===filter?'active':'',label);b.onclick=()=>{filter=value;render()};fs.append(b)}
let items=data.threads.filter(filtered).sort((a,b)=>tsOf(b)-tsOf(a)||a.display_name.localeCompare(b.display_name));
let list=document.getElementById('threads');list.replaceChildren();if(!items.length)list.append(el('div','empty','Brak rozmów. Nowe dopasowania są na górze, a pojawią się tu po pierwszej wiadomości.'));
for(let t of items){let b=el('button','thread'+(selected===t.id?' selected':''));let top=el('div','row');let nm=el('span','tname');nm.append(avatarFor(t));if(t.state==='needs_reply')nm.append(el('span','dot',''));nm.append(document.createTextNode(t.display_name));top.append(nm,t.plan?planChip(t.plan):el('span','status',statuses[t.state]||t.state));b.append(top,el('div','preview',t.latest_message||'Brak wiadomości'),el('div','mutedline',t.message_count+' wiadomości'+(t.outcomes.length?' • '+t.outcomes.join(', '):'')));b.onclick=()=>choose(t.id);list.append(b)}
document.getElementById('totals').textContent=data.threads.filter(isConv).length+' rozmów • '+data.threads.filter(t=>t.state==='needs_reply').length+' do odpowiedzi';
let t=threadById();renderProfile(t);if(!t){document.getElementById('title').textContent='Wybierz rozmowę';return}
document.getElementById('title').textContent=t.display_name+(t.profile?.age?', '+t.profile.age:'');document.getElementById('chatmeta').textContent=(t.profile?.bio||'').slice(0,70)||(t.platform==='tinder'?'Tinder':t.state_reason);document.getElementById('chatavatar').replaceChildren(avatarFor(t,'head'));document.getElementById('chatstatus').textContent=statuses[t.state]||t.state;
let messages=document.getElementById('messages');let keepScroll=messages.scrollTop;messages.replaceChildren();let history=data.messages[t.id]||[];if(!history.length){let hero=el('div','matchhero');let u=safeImg(t.profile?.photos?.[0]);if(u){hero.append(cachedImg('hero:'+t.id,u,'',t.display_name))}else hero.append(avatarFor(t,'hero'));hero.append(el('b','','Dopasowaliście się z '+t.display_name+(t.matched_at?' '+fmtDate(t.matched_at):'')),el('div','','Napisz pierwszą wiadomość. Agent nie wymyśla otwarcia za Ciebie: zacznij od czegoś z jej profilu.'));messages.append(hero)}else if(t.matched_at)messages.append(el('div','matchline','Dopasowaliście się '+fmtDate(t.matched_at)));
history.forEach((m,i)=>{let b=el('div','bubble'+(m.sender==='you'?' you':''));b.title=m.created_at?new Date(m.created_at).toLocaleString():'';b.append(el('div','',m.body));messages.append(b);if(i===history.length-1&&m.sender==='you')messages.append(el('div','sent','Wysłano'))});if(scrollKey!==t.id+':'+history.length){messages.scrollTop=messages.scrollHeight;scrollKey=t.id+':'+history.length}else messages.scrollTop=keepScroll;
let composer=document.getElementById('composer');composer.replaceChildren();let curr=data.drafts.find(d=>d.thread_id===t.id&&d.status==='pending'&&d.anchor_message_id===t.latest_message_id);
let cerr=el('p','cerr');cerr.hidden=true;const fail=e=>{cerr.hidden=false;cerr.textContent=ERR_PL[e.message]||e.message};
const send=async(path,payload,btn)=>{if(btn)btn.disabled=true;cerr.hidden=true;try{await api(path,'POST',payload);await refresh()}catch(e){fail(e);if(btn)btn.disabled=false}};
if(t.state==='needs_reply'&&curr){let head=el('div','dhead');head.append(el('b','',t.automatic_sending?'Autopilot wyśle tę odpowiedź sam':'Szkic odpowiedzi'),el('span','muted','Możesz poprawić tekst przed wysłaniem'));composer.append(head);
 if(!['demo_placeholder','model_error'].includes(curr.generator)){let ta=el('textarea','draftedit');ta.id='draft-edit';ta.value=DRAFT_EDITS.get(curr.id)??curr.body;ta.rows=Math.min(6,Math.max(2,Math.ceil(ta.value.length/60)));ta.maxLength=1000;ta.oninput=()=>DRAFT_EDITS.set(curr.id,ta.value);
  ta.onkeydown=e=>{if(e.key==='Enter'&&(e.metaKey||e.ctrlKey)){e.preventDefault();yes.click()}};composer.append(ta);
  let row=el('div','controls');let yes=el('button','primary','Wyślij');yes.title='Ctrl/Cmd + Enter';yes.onclick=()=>{let body=ta.value.trim();if(!body)return fail({message:'Wiadomość jest pusta.'});send('/api/drafts/'+curr.id+'/approve',body!==curr.body?{body}:undefined,yes).then(()=>DRAFT_EDITS.delete(curr.id))};
  let again=el('button','secondary','Napisz inaczej');again.onclick=()=>{DRAFT_EDITS.delete(curr.id);send('/api/threads/'+encodeURIComponent(t.id)+'/regenerate',undefined,again)};
  let no=el('button','secondary','Odrzuć');no.onclick=()=>{DRAFT_EDITS.delete(curr.id);send('/api/drafts/'+curr.id+'/reject',undefined,no)};row.append(yes,again,no);composer.append(row)}
 else composer.append(el('p','', 'Podłącz model AI w ustawieniach serwera, żeby powstawały pełne szkice.'))}
else if(t.state==='needs_reply'){composer.append(el('p','',data.llm_enabled?'Szkic się przygotowuje. Pojawi się tu za chwilę.':'Podłącz model AI, żeby powstawały szkice.'))}
else if(t.state==='new_match'){composer.append(el('p','', 'Nowe dopasowanie. Pierwszą wiadomość napisz sam w Tinderze, najlepiej nawiązując do czegoś z jej profilu. Od jej odpowiedzi szkice przygotuje Iskra.'))}
else if(t.state==='waiting'){composer.append(el('p','', 'Ostatnia wiadomość jest Twoja. Czekamy na odpowiedź, bez dopisywania kolejnych.'))}
else composer.append(el('p','',t.state_reason));
composer.append(cerr);
let ctrl=el('div','controls minor');let pause=el('button','linkish',t.user_paused?'Wznów tę rozmowę':'Wstrzymaj tę rozmowę');pause.onclick=()=>flags(t.id,{paused:!t.user_paused});let archive=el('button','linkish',t.user_archived?'Przywróć z archiwum':'Archiwizuj');archive.onclick=()=>flags(t.id,{archived:!t.user_archived});let del=el('button','linkish','Usuń dane rozmowy');del.onclick=async()=>{if(confirm('Usunąć zapisane dane tej rozmowy? Nie zaimportujemy jej ponownie.')){await api('/api/threads/'+encodeURIComponent(t.id),'DELETE');selected=null;await refresh()}};ctrl.append(pause,archive,del);
if(['telegram','tinder'].includes(t.platform)){let grant=el('button','linkish',t.automatic_sending?'Autopilot: włączony':'Autopilot w tej rozmowie');grant.onclick=()=>showGrant(t);ctrl.append(grant)}
composer.append(ctrl);
let needs=data.drafts.find(d=>d.thread_id===t.id&&d.anchor_message_id===t.latest_message_id&&['needs_user','no_reply'].includes(d.status));if(needs)composer.append(el('p','',(needs.status==='no_reply'?'Iskra proponuje nie odpisywać: ':'Potrzebna Twoja decyzja: ')+needs.body));
renderPlan(t);let facts=document.getElementById('facts');facts.replaceChildren();let kv=el('dl','kv');const row=(k,v)=>{if(v===undefined||v===null||v==='')return;kv.append(el('dt','',k),el('dd','',v))};
row('Stan',statuses[t.state]||t.state);row('Powód',t.state_reason);row('Wiadomości',t.message_count);row('Następne działanie',t.next_action);row('Dostęp',t.source_visibility);for(let m of data.memory[t.id]||[])row(m.kind,m.value);facts.append(kv);
let out=document.getElementById('outcomes');out.replaceChildren();let notes=(data.outcome_details[t.id]||[]);if(!notes.length)out.append(emptyCard('Na razie nic. Tu pojawią się potwierdzone ustalenia, np. termin spotkania.'));for(let n of notes){let r=el('div','oc');r.append(el('b','',n.kind),el('div','',n.body));out.append(r)}
updateSystem();document.getElementById('pause-all').textContent=data.settings.paused?'Wznów agenta':'Wstrzymaj agenta';
}
async function flags(thread_id,fields){try{await api('/api/threads/'+thread_id+'/flags','POST',fields);await refresh()}catch(e){document.getElementById('status').textContent=e.message}}
async function act(path){try{let r=await api(path,'POST');document.getElementById('status').textContent=JSON.stringify(r);await refresh()}catch(e){document.getElementById('status').textContent=e.message}}
let lastSig='',scrollKey='';
function dataSig(d){return JSON.stringify([d.threads,d.messages,d.drafts,d.grants,d.memory,d.settings,d.llm_enabled,d.connections,d.tinder.configured,d.tinder.connections.map(c=>[c.id,c.enabled,c.error,c.auto_send,c.bio_mode,c.bio_disclosure,c.last_sync]),{...d.stats,tinder_requests:null}])}
function updateSystem(){let s=document.getElementById('system');if(s&&data)s.textContent='Tryb: '+data.settings.mode+' • Worker: '+(data.worker.running?'działa':'wyłączony')+' • LLM: '+(data.llm_enabled?'skonfigurowany':'brak')+(data.worker.error?' • '+data.worker.error:'')}
async function refresh(){let next=await api('/api/state');let sig=dataSig(next);data=next;if(!selected||!data.threads.some(t=>t.id===selected)){let c=data.threads.filter(isConv).sort((a,b)=>tsOf(b)-tsOf(a))[0];selected=c?c.id:null}
if(sig===lastSig||document.activeElement?.id==='draft-edit'){updateSystem();return}lastSig=sig;let side=document.getElementById('threads').parentElement,top=side.scrollTop,rost=document.getElementById('roster').scrollLeft;render();side.scrollTop=top;document.getElementById('roster').scrollLeft=rost}
document.getElementById('sync').onclick=async()=>{let b=document.getElementById('sync');b.disabled=true;try{await act('/api/sync')}finally{b.disabled=false}};

function field(label,value,type='text'){let wrap=el('label','fact',label);wrap.style.display='block';let input=el('input','inp');input.type=type;if(type==='checkbox'){input.checked=!!value;input.className=''}else input.value=value;wrap.append(input);return [wrap,input]}
function panel(title){document.getElementById('panel-title').textContent=title;let p=document.getElementById('panel-content');p.replaceChildren();document.getElementById('panel').showModal();return p}
function group(label,desc,control){let g=el('div','group');let l=el('div','glabel',label);g.append(l);if(desc)g.append(el('div','gdesc',desc));g.append(control);return g}
function toggle(label,checked,desc){let w=el('label','switchrow');let t=el('div','');t.append(el('div','glabel',label));if(desc)t.append(el('div','gdesc',desc));let i=el('input','');i.type='checkbox';i.checked=!!checked;let s=el('span','switch');w.append(t,i,s);return [w,i]}
function chip(text,kind){return el('span','chip '+kind,text)}
const tinderErrors={inbox_access_denied:'Tinder odrzucił dostęp do skrzynki (401). Połącz ponownie z aktualnym tokenem.',session_expired_or_account_changed:'Sesja wygasła albo zmieniło się konto. Podaj nowy token.',session_expired_or_access_denied:'Sesja wygasła. Podaj nowy token.',restriction_requires_manual_review:'Tinder wymaga sprawdzenia konta w oficjalnej aplikacji.',rate_limited:'Tinder poprosił o przerwę. Synchronizacja wznowi się sama.',local_request_budget:'Osiągnięto lokalny limit zapytań. Synchronizacja wznowi się sama.',source_sync_failed:'Ostatnia synchronizacja się nie udała. Spróbuje ponownie.',circuit_open_requires_review:'Zbyt wiele błędów z rzędu. Sprawdź połączenie i połącz ponownie.',repeated_rate_limits_requires_review:'Wielokrotne ograniczenia od Tinder. Poczekaj przed ponownym połączeniem.'};
function showSettings(tab='general'){setView('settings');let p=document.getElementById('settings-view');p.replaceChildren();let cfg=data.settings;let result=el('div','mresult');
let tabs=[['general','Ogólne','Tryb pracy, język i jak długo trzymamy rozmowy.'],['goal','Cel i spotkania','Dokąd bot prowadzi rozmowę, w jakim tempie i kiedy masz czas.'],['style','Styl i profil','Jak piszesz i co bot może o Tobie powiedzieć.'],['tinder','Tinder','Połączenie konta, token i pełny import historii.'],['accounts','Konto','Wylogowanie, konto Iskra i połączone konta.']];let shell=el('div','sv');let bar=el('nav','sv-nav');bar.setAttribute('aria-label','Sekcje ustawień');let main=el('div','sv-main');let head=el('div','sv-head');let body=el('div','sect');main.append(head,body,result);shell.append(bar,main);p.append(shell);
let fields={};
function build(){bar.replaceChildren();bar.append(el('div','sv-title','Ustawienia'));for(let [k,l] of tabs){let b=el('button','sv-item'+(tab===k?' active':''),l);b.onclick=()=>{tab=k;build()};bar.append(b)}let cur=tabs.find(x=>x[0]===tab)||tabs[0];head.replaceChildren(el('h2','',cur[1]),el('p','',cur[2]));body.replaceChildren();result.textContent='';fields={};
if(tab==='general'){
 let mode=el('select','inp');for(let [v,l] of [['supervised','Nadzorowany: zatwierdzasz każdy szkic'],['simulation','Symulacja: tylko fikcyjne wiadomości'],['authorized_autonomy','Autonomiczny: automatyczne odpowiedzi w zgodnych rozmowach']]){let o=el('option','',l);o.value=v;o.selected=cfg.mode===v;mode.append(o)}fields.mode=mode;
 body.append(group('Tryb pracy agenta','Autonomia wymaga zgody uczestnika i ujawnienia w danej rozmowie oraz aktywnego konta.',mode));
 let lang=el('input','inp');lang.value=cfg.language;fields.language=lang;body.append(group('Język odpowiedzi','auto = język rozmówcy; można wpisać np. pl albo en.',lang));
 let ret=el('input','inp');ret.type='number';ret.min=1;ret.max=365;ret.value=cfg.retention_days;fields.retention_days=ret;body.append(group('Retencja rozmów (dni)','Rozmowy bez wiadomości od tylu dni są usuwane automatycznie. Maksymalnie 365.',ret));
 let [w,em]=toggle('Powiadomienia e-mail',cfg.email,'Wysyłaj powiadomienia o nowych szkicach i wynikach.');fields.email=em;body.append(w);
 let save=el('button','primary','Zapisz ustawienia');save.onclick=()=>saveSettings();let foot=el('div','mfoot');foot.append(save);body.append(foot)}
if(tab==='goal'){

 let goal=el('select','inp');for(let [v,l] of [['date','Spotkanie na żywo (Instagram jako plan B)'],['date_or_instagram','Spotkanie albo Instagram'],['instagram','Instagram'],['chat','Tylko rozmowa, bez zaproszeń']]){let o=el('option','',l);o.value=v;o.selected=(cfg.goal||'date')===v;goal.append(o)}fields.goal=goal;body.append(group('Cel','Bot prowadzi rozmowę w stronę tego celu, ale odmowa lub wahanie zawsze wygrywa.',goal));
 let pace=el('select','inp');for(let [v,l] of [['slow','Spokojne: zaproszenie po ok. 7 wymianach'],['normal','Normalne: po ok. 5 wymianach'],['fast','Szybkie: po ok. 3 wymianach']]){let o=el('option','',l);o.value=v;o.selected=(cfg.pace||'normal')===v;pace.append(o)}fields.pace=pace;body.append(group('Tempo','Tylko gdy widać zainteresowanie. Jeśli sama wspomni o wyjściu, bot zaproponuje wcześniej.',pace));
 let [iw,ig]=toggle('Instagram jako lżejszy krok',cfg.allow_instagram!==false,'Gdy odłoży spotkanie na „kiedyś", a rozmowa jest ciepła.');fields.allow_instagram=ig;body.append(iw);
 let av=el('input','inp');av.value=cfg.availability||'';fields.availability=av;body.append(group('Kiedy masz czas','Bot proponuje terminy tylko z tego opisu.',av));
 let ideas=el('textarea','inp');ideas.rows=5;ideas.value=(cfg.date_ideas&&cfg.date_ideas.length?cfg.date_ideas:['kawa albo matcha na mieście','spacer z kawą na wynos','piwo albo wino w luźnym barze','wystawa, targi albo coś w tym stylu','planszówki w barze','lody albo gofry i spacer']).join('\n');fields.date_ideas=ideas;body.append(group('Pomysły na pierwsze spotkanie','Jeden pomysł w linii. Bot dobiera ten, który pasuje do Waszej rozmowy.',ideas));
 let save=el('button','primary','Zapisz ustawienia');save.onclick=()=>saveSettings();let foot=el('div','mfoot');foot.append(save);body.append(foot)}
if(tab==='style'){
 let lib=el('div','scard');lib.append(el('div','glabel','Biblioteka stylu'),el('div','gdesc','Ładowanie...'));body.append(lib);
 let style=el('input','inp');style.value=cfg.style;fields.style=style;
 api('/api/style').then(r=>{lib.replaceChildren(el('div','glabel','Biblioteka stylu'),el('div','gdesc','Wzorce: '+r.corpus_pairs+' par z korpusu (w tym '+r.corpus_pl+' po polsku) + '+r.own_pairs+' Twoich prawdziwych odpowiedzi z Tindera. Przy każdej wiadomości bot dobiera najbardziej podobne sytuacje jako wzór tonu, nie faktów.'),el('div','gdesc','Zmierzony styl ('+(r.stats.based_on==='own_messages'?'z Twoich wiadomości':'z korpusu')+'): mediana '+r.stats.median_chars+' znaków, '+r.stats.lowercase_start_pct+'% od małej litery, '+r.stats.question_pct+'% kończy się pytaniem, emoji '+r.stats.emoji_pct+'%.'));let use=el('button','secondary','Wstaw sugerowany opis stylu');use.onclick=()=>{style.value=r.suggested_style};lib.append(use)}).catch(e=>{lib.replaceChildren(el('div','gdesc',e.message))});body.append(group('Styl pisania','Krótki opis tonu, np. „krótko, swobodnie, bez wymuszonych pytań".',style));
 let profile=el('textarea','inp');profile.rows=7;profile.value=JSON.stringify(cfg.profile,null,2);fields.profile=profile;body.append(group('Zweryfikowane fakty o Tobie (JSON)','Tylko to, co sam podajesz. Agent nie dopisuje faktów ze starych wiadomości.',profile));
 let fb=el('textarea','inp');fb.rows=4;fb.value=cfg.feedback.join('\n');fields.feedback=fb;body.append(group('Preferencje stylu','Jedna preferencja w linii.',fb));
 let save=el('button','primary','Zapisz ustawienia');save.onclick=()=>saveSettings();let foot=el('div','mfoot');foot.append(save);body.append(foot)}
if(tab==='tinder')buildTinder();
if(tab==='accounts'){
 let me=el('div','scard');me.append(el('div','glabel','Sesja'),el('div','gdesc','Wylogowanie kończy sesję w tej przeglądarce. Bot dalej działa w tle zgodnie z ustawieniami.'));let row=el('div','btnrow');let lo=el('button','secondary','Wyloguj się');lo.onclick=logoutNow;row.append(lo);if(data.account_url){let ac=el('a','secondary','Konto Iskra');ac.href=data.account_url+'/konto';row.append(ac)}me.append(row);body.append(me);
 body.append(el('div','glabel','Połączone konta'),el('div','gdesc','Odwołanie połączenia zatrzymuje agenta dla tego konta. Dane rozmów zostają, dopóki ich nie usuniesz.'));
 if(!data.connections.length)body.append(el('div','empty','Brak połączonych kont.'));
 for(let c of data.connections){let row=el('div','acct');row.append(el('div','acctname',c.id),chip(c.enabled?'aktywne':'wyłączone',c.enabled?'ok':'warn'));let b=el('button','secondary danger','Odwołaj');b.onclick=async()=>{if(!confirm('Odwołać połączenie '+c.id+'?'))return;await api('/api/connections/'+encodeURIComponent(c.id)+'/revoke','POST');await refresh();showSettings('accounts')};row.append(b);body.append(row)}}}
async function saveSettings(){try{let next={...cfg};const v=k=>fields[k];
 if(v('mode'))next.mode=v('mode').value;if(v('language'))next.language=v('language').value.trim();if(v('retention_days'))next.retention_days=Number(v('retention_days').value);if(v('email'))next.email=v('email').checked;
 if(v('goal'))next.goal=v('goal').value;if(v('pace'))next.pace=v('pace').value;if(v('allow_instagram'))next.allow_instagram=v('allow_instagram').checked;if(v('availability'))next.availability=v('availability').value.trim();if(v('date_ideas'))next.date_ideas=v('date_ideas').value.split('\n').map(x=>x.trim()).filter(Boolean);
 if(v('style'))next.style=v('style').value;if(v('profile'))next.profile=JSON.parse(v('profile').value||'{}');if(v('feedback'))next.feedback=v('feedback').value.split('\n').filter(Boolean);
 await api('/api/settings','PUT',next);await refresh();cfg=data.settings;result.className='mresult ok';result.textContent='Zapisano.'}catch(e){result.className='mresult err';result.textContent=e.message.startsWith('Unexpected token')||e.message.includes('JSON')?'Fakty o Tobie muszą być poprawnym JSON-em, np. {"miasto": "Warszawa"}.':e.message}}
function buildTinder(){
 let cons=data.tinder.connections;let ts=data.tinder;
 let tok=el('div','scard');tok.append(el('div','glabel','Token Tindera'));
 if(ts.token_source){let row=el('div','row');row.append(el('div','gdesc',(ts.token_source==='vault'?'Zapisany w tym panelu, zaszyfrowany (AES-256).':'Ustawiony przez administratora serwera.')+' Odcisk: …'+(ts.token_fingerprint||'')),chip('zapisany','ok'));tok.append(row);
  if(ts.token_source==='vault'){let del=el('button','secondary danger','Usuń token i rozłącz');del.onclick=async()=>{if(!confirm('Usunąć token? Bot przestanie synchronizować i wysyłać.'))return;await api('/api/tinder/token','DELETE');await refresh();showSettings('tinder')};tok.append(del)}}
 else tok.append(el('div','gdesc','Brak tokena. Wklej go poniżej, żeby połączyć konto.'));
 if(!ts.enabled)tok.append(el('div','callout warn','Integracja Tinder jest wyłączona na tym serwerze (TINDER_ENABLED).'));
 if(!ts.vault_ready&&ts.token_source!=='env')tok.append(el('div','callout warn','Serwer nie ma klucza szyfrowania, więc nie zapisze tokena. Skontaktuj się z obsługą.'));
 let how=el('details','howto');how.append(el('summary','','Skąd wziąć token? (2 minuty)'));for(let s of ['Na komputerze otwórz tinder.com i zaloguj się.','Otwórz narzędzia deweloperskie: Chrome F12, Safari Cmd+Opcja+I (włącz w Ustawieniach → Zaawansowane).','Zakładka Application (Chrome) albo Storage (Safari) → Local Storage → https://tinder.com.','Znajdź klucz TinderWeb/APIToken i skopiuj jego wartość (zwykle 36 znaków).','Wklej poniżej. Nie wysyłaj tokena nikomu i nigdzie indziej.'])how.append(el('div','sig','• '+s));tok.append(how);
 let tin=el('input','inp');tin.type='password';tin.autocomplete='off';tin.placeholder=ts.token_source?'Wklej nowy token, żeby go podmienić':'Wklej token';tin.spellcheck=false;
 let [tow,town]=toggle('To jest moje konto Tinder',false);let [tak,tack]=toggle('Rozumiem, że integracja jest nieoficjalna i Tinder może ograniczyć konto',false);let [tsd,tsdc]=toggle('Zgadzam się na przetwarzanie danych z rozmów, które mogą dotyczyć życia intymnego (art. 9 RODO). Zgodę wycofam, usuwając token.',false);
 let tres=el('div','mresult');let tsave=el('button','primary','Zapisz i połącz');tsave.disabled=!ts.enabled||!ts.vault_ready;
 tsave.onclick=async()=>{tsave.disabled=true;tres.className='mresult';tres.textContent='Sprawdzam token w Tinderze...';try{await api('/api/tinder/token','POST',{token:tin.value,account_owned:town.checked,acknowledge_unofficial:tack.checked,sensitive_data:tsdc.checked});tin.value='';await refresh();showSettings('tinder')}catch(e){tres.className='mresult err';tres.textContent=e.message;tsave.disabled=false}finally{tin.value=''}};
 tok.append(tin,tow,tak,tsd,tsave,tres);body.append(tok);
 for(let c of cons){let card=el('div','scard');let top=el('div','row');top.append(el('b','',c.id.replace('tinder:','Konto ').slice(0,28)+'…'),chip(c.enabled&&!c.error?'połączone':c.error?'wstrzymane':'wyłączone',c.enabled&&!c.error?'ok':c.error?'err':'warn'));card.append(top);
  card.append(el('div','gdesc','Ostatnia synchronizacja: '+(c.last_sync?new Date(c.last_sync).toLocaleString():'jeszcze nie było')));
  if(c.error)card.append(el('div','callout err',tinderErrors[c.error]||('Wymaga uwagi: '+c.error)));
  const setAuto=async patch=>{await api('/api/tinder/connections/'+encodeURIComponent(c.id)+'/automation','PUT',patch);await refresh();showSettings('tinder')};
  let ap=el('div','autobox');ap.append(el('div','glabel','Autopilot'),el('div','gdesc','Bot sam odpisuje we wszystkich rozmowach, w których ktoś Ci odpisał. Pierwszą wiadomość do nowego dopasowania piszesz Ty.'));
  let live=c.auto_send&&c.bio_mode&&c.bio_disclosure;ap.append(el('div','callout '+(live?'ok':'warn'),live?'Autopilot działa we wszystkich rozmowach.':'Autopilot jest wyłączony. Spełnij oba warunki poniżej.'));
  let bio=el('div','autostep');bio.append(el('b','',(c.bio_disclosure?'✓ ':'1. ')+'Informacja o AI w Twoim bio na Tinderze'),el('div','gdesc',c.bio_disclosure?'Wykryliśmy ją w bio. Sprawdzamy przy każdej synchronizacji; jeśli ją usuniesz, autopilot się zatrzyma.':'Nie widzimy jej w bio. Dodaj w aplikacji Tinder zdanie ze słowem „AI”, np.:'));
  if(!c.bio_disclosure){let ex=el('div','bioex','Używam AI czasami, a ty? 🤖');bio.append(ex,el('div','gdesc','Po zmianie bio kliknij Synchronizuj.'))}
  let [bw,bc]=toggle('W moim bio jest informacja, że używam AI',!!c.bio_mode);bc.onchange=()=>setAuto({bio_mode:bc.checked});bio.append(bw);ap.append(bio);
  let go=el('div','autostep');go.append(el('b','','2. Włącz automatyczne wysyłanie'));let ar=el('button',c.auto_send?'secondary':'primary',c.auto_send?'Wyłącz autopilota':'Włącz autopilota');ar.onclick=()=>setAuto({enabled:!c.auto_send});go.append(ar);ap.append(go);
  ap.append(el('div','gdesc','Bezpieczniki: jeśli ktoś zapyta o bota, Iskra odpowie szczerze i na luzie, że czasem pomaga Ci AI, i pisze dalej; jeśli ktoś się sprzeciwi, rozmowa wraca do Ciebie. Bot nie dopisuje kolejnych wiadomości, gdy ostatnia jest Twoja. Obowiązują limity zapytań konta. Pojedynczą rozmowę wyłączysz pod czatem („Autopilot w tej rozmowie”), a wszystko naraz przyciskiem „Wstrzymaj agenta”.'));
  card.append(ap);body.append(card)}
 let load=el('div','scard');load.append(el('div','glabel','Pełny import historii'),el('div','gdesc','Pobiera w tle wszystkie dopasowania, rozmowy i zdjęcia, także te usunięte wcześniej przez retencję. Trwa od kilku do kilkunastu minut, na wyższych limitach jednorazowo; potem bot wraca do zwykłych limitów. Zwykłe odświeżanie robi przycisk Synchronizuj na liście rozmów.'));let note=el('div','mresult');let lb=el('button','primary','Uruchom pełny import');lb.disabled=!data.tinder.configured;lb.onclick=async()=>{lb.disabled=true;try{let r=await api('/api/tinder/restore-deleted','POST');note.className='mresult ok';note.textContent='Import ruszył w tle (odblokowano rozmów: '+r.restored+'). Rozmowy będą się pojawiać stopniowo. Koniec importu zobaczysz w Aktywności jako tinder_initial_import_done.';setTimeout(()=>refresh().catch(()=>{}),15000)}catch(e){note.className='mresult err';note.textContent=e.message}finally{lb.disabled=false}};load.append(lb,note);body.append(load);
 if(!data.tinder.configured)return;let conn=el('div','scard');conn.append(el('div','glabel',cons.length?'Połącz ponownie':'Połącz konto Tinder'),el('div','gdesc','Połączenie włącza automatyczne odpowiedzi tylko dla tego konta Tinder, w rozmowach ze zgodą i ujawnieniem. Integracja jest nieoficjalna i Tinder może ograniczyć konto.'));
 let [ow,owned]=toggle('To jest moje konto',false);let [aw,ack]=toggle('Rozumiem, że integracja jest nieoficjalna',false);let cres=el('div','mresult');let cb=el('button','primary',cons.length?'Połącz ponownie':'Połącz Tinder');cb.disabled=!data.tinder.configured;
 cb.onclick=async()=>{cb.disabled=true;try{await api('/api/tinder/connect','POST',{account_owned:owned.checked,acknowledge_unofficial:ack.checked});await refresh();showSettings('tinder')}catch(e){cres.className='mresult err';cres.textContent=e.message;cb.disabled=false}};conn.append(ow,aw,cb,cres);body.append(conn)}
build()}
function showGrant(t){let p=panel('Autopilot: '+t.display_name);let old=data.grants.find(g=>g.thread_id===t.id);let conn=data.tinder.connections.find(c=>c.id===t.connection_id)||{};
let bioOn=t.platform==='tinder'&&conn.auto_send&&conn.bio_mode&&conn.bio_disclosure;
if(bioOn){let off=old&&!old.enabled;p.append(el('p','',off?'Autopilot jest w tej rozmowie wyłączony'+(old.participant_consent===0&&old.disclosed===0?' (np. zapytała o AI albo wyłączyłeś go ręcznie).':'.'):'Autopilot działa tu dzięki informacji o AI w Twoim bio.'));
 let b=el('button',off?'primary':'secondary',off?'Włącz z powrotem':'Wyłącz w tej rozmowie');b.onclick=async()=>{if(off)await api('/api/threads/'+encodeURIComponent(t.id)+'/grant','PUT',{enabled:true,participant_consent:true,disclosed:true});else await api('/api/threads/'+encodeURIComponent(t.id)+'/grant','PUT',{enabled:false,participant_consent:false,disclosed:false});await refresh();document.getElementById('panel').close()};p.append(b);return}
old=old||{};p.append(el('p','','Autopilot wysyła odpowiedzi bez Twojego kliknięcia. Najprościej włączyć go dla wszystkich rozmów naraz: dodaj informację o AI do bio (Ustawienia → Tinder). Możesz też włączyć go tylko tu, jeśli ta osoba wie, że pomaga Ci AI.'));
let fields={};for(let [k,lab] of [['disclosed','Ta osoba wie, że odpowiedzi pisze lub pomaga pisać AI'],['participant_consent','Nie ma nic przeciwko'],['enabled','Włącz autopilota w tej rozmowie']]){let[w,i]=field(lab,old[k],'checkbox');fields[k]=i;p.append(w)}
if(t.platform==='tinder'&&!conn.auto_send)p.append(el('div','callout warn','Automatyczne wysyłanie jest wyłączone dla całego konta (Ustawienia → Tinder).'));
let save=el('button','primary','Zapisz');save.onclick=async()=>{await api('/api/threads/'+encodeURIComponent(t.id)+'/grant','PUT',Object.fromEntries(Object.entries(fields).map(([k,v])=>[k,v.checked])));await refresh();document.getElementById('panel').close()};p.append(save)}
function pendingQueue(){if(!data)return[];return data.threads.filter(t=>t.state==='needs_reply').map(t=>[t,data.drafts.find(d=>d.thread_id===t.id&&d.status==='pending'&&d.anchor_message_id===t.latest_message_id&&!['demo_placeholder','model_error'].includes(d.generator))]).filter(x=>x[1]).sort((a,b)=>tsOf(b[0])-tsOf(a[0]))}
function showQueue(skip=new Set()){let q=pendingQueue().filter(([t])=>!skip.has(t.id));let p=panel(q.length?'Odpisz po kolei · zostało '+q.length:'Wszystko odpisane');if(!q.length){p.append(el('p','','Nie ma więcej szkiców do wysłania. Nowe pojawią się, gdy ktoś odpisze.'));return}
let [t,d]=q[0];let who=el('div','qwho');who.append(avatarFor(t,'queue'),el('b','',t.display_name+(t.profile?.age?', '+t.profile.age:'')));p.append(who);
let hist=el('div','qhist');for(let m of (data.messages[t.id]||[]).slice(-4))hist.append(el('div','bubble'+(m.sender==='you'?' you':''),m.body));p.append(hist);
let ta=el('textarea','draftedit');ta.value=d.body;ta.rows=3;ta.maxLength=1000;p.append(ta);let err=el('p','cerr');err.hidden=true;
let row=el('div','controls');let yes=el('button','primary','Wyślij i dalej');let next=el('button','secondary','Pomiń');let again=el('button','secondary','Napisz inaczej');
yes.onclick=async()=>{let body=ta.value.trim();if(!body)return;yes.disabled=true;try{await api('/api/drafts/'+d.id+'/approve','POST',body!==d.body?{body}:undefined);await refresh();showQueue(skip)}catch(e){err.hidden=false;err.textContent=ERR_PL[e.message]||e.message;yes.disabled=false}};
next.onclick=()=>{skip.add(t.id);showQueue(skip)};again.onclick=async()=>{again.disabled=true;try{await api('/api/threads/'+encodeURIComponent(t.id)+'/regenerate','POST');await refresh();skip.add(t.id);showQueue(skip)}catch(e){err.hidden=false;err.textContent=e.message;again.disabled=false}};
ta.onkeydown=e=>{if(e.key==='Enter'&&(e.metaKey||e.ctrlKey)){e.preventDefault();yes.click()}};row.append(yes,next,again);p.append(row,err);ta.focus()}
async function pauseAll(){await api('/api/settings','PUT',{...data.settings,paused:!data.settings.paused});await refresh()}
function showActivity(){let p=panel('Activity & reliability');p.append(el('p','','Last worker tick: '+data.worker.last_tick));for(let a of data.activity)p.append(el('p','fact',a.ts+' · '+(a.thread_id||'system')+' · '+a.event+' · '+a.detail));p.append(el('h2','','Metrics'));for(let m of data.metrics)p.append(el('p','fact',m.name+': '+m.total+' ('+m.samples+' samples)'));p.append(el('h2','','Delivery status'));for(let a of data.actions)p.append(el('p','fact',a.thread_id+' · '+a.status));for(let o of data.outbox)p.append(el('p','fact','Notification '+o.id+': '+o.status+' · attempts '+o.attempts));}
function connBanner(on,text){let b=document.getElementById('conn-banner');if(!b){b=el('div','connbanner');b.id='conn-banner';b.setAttribute('role','status');document.body.prepend(b)}b.hidden=!on;if(text)b.textContent=text}
let failures=0;
async function safeRefresh(){try{await refresh();if(failures)connBanner(false);failures=0}catch(e){failures++;
 if(e.status===401){location.reload();return}
 connBanner(true,data?'Brak połączenia z serwerem. Pokazuję ostatnie dane, ponawiam…':'Łączę z serwerem… Jeśli właśnie był restart, to potrwa kilkanaście sekund.')}}
safeRefresh();setInterval(()=>{if(!document.getElementById('panel').open&&!document.getElementById('viewer')?.open)safeRefresh()},5000)


document.getElementById('tab-settings').addEventListener('click',()=>showSettings());document.getElementById('queue-btn')?.addEventListener('click',()=>showQueue());document.getElementById('logout').addEventListener('click',logoutNow);document.getElementById('open-activity').addEventListener('click',showActivity);document.getElementById('pause-all').addEventListener('click',pauseAll);document.getElementById('close-panel').addEventListener('click',()=>document.getElementById('panel').close());

let view='chats';
function setView(v){view=v;for(let [id,name] of [['tab-chats','chats'],['tab-stats','stats'],['tab-settings','settings']])document.getElementById(id).classList.toggle('active',v===name);document.querySelector('main').hidden=v!=='chats';document.getElementById('roster-wrap').hidden=v!=='chats';renderOnboarding();document.getElementById('stats-view').hidden=v!=='stats';document.getElementById('settings-view').hidden=v!=='settings';if(v==='stats')renderStats()}
async function logoutNow(){try{await api('/auth/logout','POST')}catch(e){}location.href=data&&data.account_url?data.account_url+'/zaloguj':'/'}
function renderRoster(){let box=document.getElementById('roster');box.replaceChildren();if(!data)return;
let todo=data.threads.filter(t=>t.state==='new_match').sort((a,b)=>matchedOf(b)-matchedOf(a)),reply=data.threads.filter(t=>t.state==='needs_reply').sort((a,b)=>tsOf(b)-tsOf(a));
document.getElementById('roster-title').textContent='Do napisania · '+todo.length+' nowych'+(reply.length?' · '+reply.length+' czeka na Twoją odpowiedź':'');
let qn=pendingQueue().length,qb=document.getElementById('queue-btn');if(qb){qb.hidden=!qn;qb.textContent='Odpisz po kolei ('+qn+')'}
if(!todo.length&&!reply.length){box.append(el('div','roster-empty','Wszystko odpisane. Nowe dopasowania pojawią się tutaj.'));return}
for(let t of [...todo,...reply]){let b=el('button','rost'+(selected===t.id?' sel':''));let u=safeImg(t.profile?.photos?.[0]);
if(u){b.append(cachedImg('roster:'+t.id,u,'rimg',t.display_name))}else b.append(el('div','rinit',(t.display_name||'?').slice(0,1).toUpperCase()));
b.append(el('span','rtag'+(t.state==='needs_reply'?' wait':''),t.state==='needs_reply'?'ODPISZ':'NOWY'),el('div','rover',t.display_name+(t.profile?.age?', '+t.profile.age:'')));
b.onclick=()=>{setView('chats');choose(t.id)};box.append(b)}}
function tile(big,cap){let t=el('div','tile');t.append(el('div','big',big),el('div','cap',cap));return t}
function kv(k,v){let r=el('div','kv');r.append(el('span','',k),el('b','',v));return r}
function renderStats(){let root=document.getElementById('stats-view');root.replaceChildren();if(!data){root.textContent='Ładowanie...';return}let st=data.stats;if(!st){root.textContent='Brak statystyk.';return}
let sent=0,auto=0,manual=0,uncertain=0;for(let a of st.actions){if(a.status==='sent'){sent+=a.n;if(a.automatic)auto+=a.n;else manual+=a.n}if(a.status==='uncertain')uncertain+=a.n}
let rate=st.we_wrote?Math.round(100*st.they_replied/st.we_wrote)+'%':'—';
let tiles=el('div','tiles');tiles.append(tile(st.matches,'Dopasowania'),tile(st.by_state.new_match||0,'Do napisania'),tile(st.conversations_two_way,'Rozmowy z odpowiedzią'),tile(rate,'Odpowiedzi na Twoje wiadomości'),tile(sent,'Wiadomości wysłane przez agenta'),tile(st.messages_them,'Wiadomości od dopasowań'),tile(st.with_photos+'/'+st.matches,'Dopasowania ze zdjęciem'));root.append(tiles);
let fun=el('div','cardx');fun.append(el('h2','','Lejek: od dopasowania do spotkania'));let f=st.funnel||{};for(let [k,l] of [['matches','Dopasowania'],['conversations','Rozmowy'],['invite_window','W oknie na zaproszenie'],['invited','Zaproponowane spotkanie'],['agreed','Zgoda / ustalanie'],['confirmed','Spotkanie potwierdzone'],['instagram','Instagram podany']]){let row=el('div','frow');let w=Math.round(100*(f[k]||0)/Math.max(1,f.matches||1));let b=el('div','fbar');let fi=el('div','');fi.style.width=w+'%';b.append(fi);row.append(el('span','flab',l),b,el('b','',String(f[k]||0)));fun.append(row)}root.append(fun);
let c=el('div','cardx');c.append(el('h2','','Ostatnie 7 dni'));let max=Math.max(1,...st.per_day.map(d=>d.you+d.them));let bars=el('div','bars');for(let d of st.per_day){let col=el('div','bcol');let stack=el('div','bstack');let them=el('div','b-them');them.style.height=(100*d.them/max)+'%';let you=el('div','b-you');you.style.height=(100*d.you/max)+'%';stack.append(them,you);col.append(stack,el('div','blab',d.day.slice(5)));col.title=d.day+': Ty '+d.you+', oni '+d.them;bars.append(col)}c.append(bars);let lg=el('div','legend');lg.innerHTML='<span><i class="b-you"></i>Ty / agent</span><span><i class="b-them"></i>Dopasowania</span>';c.append(lg);root.append(c);
let g=el('div','grid2');let how=el('div','cardx');how.append(el('h2','','Jak to działa'));
how.append(kv('Wysłane automatycznie',auto),kv('Wysłane po Twoim zatwierdzeniu',manual),kv('Szkice oczekujące',st.drafts.pending||0),kv('Szkice odrzucone',st.drafts.rejected||0),kv('Szkice nieaktualne',st.drafts.stale||0),kv('Wysyłki niepewne (do sprawdzenia)',uncertain),kv('Tryb',data.settings.mode),kv('Agent',data.settings.paused?'wstrzymany':(data.worker.running?'działa':'wyłączony')));
if(st.tinder_requests)how.append(kv('Zapytania do Tinder (min / godz.)',st.tinder_requests.minute+' / '+st.tinder_requests.hour));
let res=el('div','cardx');res.append(el('h2','','Zweryfikowane rezultaty'));let names={instagram_shared:'Instagram podany',phone_shared:'Telefon podany',date_suggested:'Propozycja spotkania',date_tentative:'Spotkanie wstępne',date_confirmed:'Spotkanie potwierdzone',date_rescheduled:'Spotkanie przełożone',date_cancelled:'Spotkanie odwołane',outcome_uncertain:'Niepewny wynik'};let ks=Object.keys(st.outcomes);if(!ks.length)res.append(el('div','fact muted','Brak jeszcze rezultatów. Pojawią się, gdy rozmowa zawiera sprawdzalny kontakt lub plan spotkania.'));for(let k of ks)res.append(kv(names[k]||k,st.outcomes[k]));
res.append(el('h2','','Stan rozmów'));let sn={needs_reply:'Do odpowiedzi',waiting:'Czekasz na odpowiedź',new_match:'Nowe dopasowania',paused:'Wstrzymane',archived:'Archiwum',unavailable_unknown:'Dostęp niepewny',needs_review:'Do sprawdzenia',not_synced:'Niezsynchronizowane'};for(let k of Object.keys(st.by_state))res.append(kv(sn[k]||k,st.by_state[k]));
g.append(how,res);root.append(g);
let act=el('div','cardx');act.append(el('h2','','Ostatnia aktywność'));for(let a of data.activity.slice(0,10))act.append(kv(a.event+(a.thread_id?' · '+(data.threads.find(t=>t.id===a.thread_id)?.display_name||''):''),a.ts.slice(5,16).replace('T',' ')));root.append(act)}
document.getElementById('tab-chats').addEventListener('click',()=>setView('chats'));document.getElementById('tab-stats').addEventListener('click',()=>setView('stats'));

function renderOnboarding(){const box=document.getElementById('onboard');if(!box||!data)return;
 let dismissed=false;try{dismissed=localStorage.getItem('iskra-onboard-done')==='1'}catch(e){}
 const t=data.tinder||{};const steps=[
  ['Połącz konto Tinder','Wklej token w Ustawieniach. Sprawdzimy go i zaszyfrujemy.',!!t.token_source,()=>showSettings('tinder')],
  ['Ustaw styl i fakty o sobie','Opis stylu i kilka faktów, żeby szkice brzmiały jak Ty.',Object.keys(data.settings.profile||{}).length>0,()=>showSettings('style')],
  ['Uruchom pełny import','Pobierzemy dopasowania, rozmowy i zdjęcia.',(t.connections||[]).some(c=>c.last_sync),()=>showSettings('tinder')]];
 const allDone=steps.every(s=>s[2]);box.hidden=dismissed||allDone||view!=='chats';if(box.hidden)return;box.replaceChildren();
 const card=el('div','ob');card.append(el('h2','','Zacznij w 3 krokach'),el('p','','Po tych krokach bot zacznie przygotowywać szkice odpowiedzi.'));
 const close=el('button','ob-close','Ukryj');close.onclick=()=>{try{localStorage.setItem('iskra-onboard-done','1')}catch(e){}box.hidden=true};card.append(close);
 const row=el('div','ob-steps');steps.forEach(([title,desc,done,go],i)=>{const s=el('div','ob-step'+(done?' done':''));s.append(el('b','',(i+1)+'. '+title),el('small','',desc));if(!done){const b=el('button','primary',i===0?'Połącz':'Przejdź');b.onclick=go;s.append(b)}row.append(s)});card.append(row);box.append(card)}
