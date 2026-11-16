const OUTCOME_NAMES={instagram_shared:'Instagram podany',phone_shared:'Telefon podany',date_suggested:'Propozycja spotkania',date_tentative:'Spotkanie wstępne',date_confirmed:'Spotkanie potwierdzone',date_rescheduled:'Spotkanie przełożone',date_cancelled:'Spotkanie odwołane',outcome_uncertain:'Niepewny wynik'};

const OPENER='__opener__';  // anchor of a first-message draft (the conversation is still empty)
let data=null, selected=null, filter='all', DEEP=location.hash==='#stats';  // #stats: the weekly e-mail opens the panel on the statistics tab
const statuses={not_synced:'Jeszcze nie sprawdzono',new_match:'Nowy match',needs_reply:'Odpowiedź oczekuje',waiting:'Czekasz na odpowiedź',paused:'Wstrzymana',archived:'Archiwum',unavailable_unknown:'Dostęp niepewny',needs_review:'Do sprawdzenia'};
function el(tag,cls,text){let x=document.createElement(tag);if(cls)x.className=cls;if(text!==undefined)x.textContent=String(text);return x}
async function api(path,method='GET',payload){let res=await fetch(path,{method,headers:{'Content-Type':'application/json','X-Agent-Request':'dashboard'},body:payload?JSON.stringify(payload):undefined});let body=await res.json().catch(()=>({}));if(!res.ok){let d=body.detail;if(Array.isArray(d))d='Niepoprawne dane w polu: '+d.map(x=>(x.loc||[]).slice(1).join(' / ')||'?').join(', ')+'.';throw Object.assign(Error(d||res.status),{status:res.status})}return body}

function safeImg(u){try{let x=new URL(u);return x.protocol==='https:'&&(x.hostname==='gotinder.com'||x.hostname.endsWith('.gotinder.com'))?x.href:null}catch(e){return null}}
const IMG_CACHE=new Map();
function cachedImg(key,url,cls,alt){let i=IMG_CACHE.get(key);if(!i||i.dataset.src!==url){i=el('img',cls);i.src=url;i.dataset.src=url;i.decoding='async';i.referrerPolicy='no-referrer';IMG_CACHE.set(key,i)}i.className=cls;i.alt=alt||'';return i}
function avatarFor(t,place='list'){let u=safeImg(t.profile?.photos?.[0]);if(u){let i=cachedImg(place+':'+t.id,u,'avatar',t.display_name);i.style.objectFit='cover';return i}return el('span','avatar',(t.display_name||'?').slice(0,1).toUpperCase())}
const PHOTO_IDX=new Map(),DRAFT_EDITS=new Map();
const ERR_PL={'New message invalidates draft':'Przyszła nowa wiadomość, więc ten szkic jest nieaktualny. Za chwilę powstanie nowy.','Conversation content changed; regenerate draft':'Rozmowa się zmieniła. Kliknij „Napisz inaczej”.','Profile or writing preferences changed; regenerate draft':'Zmieniłeś ustawienia stylu. Kliknij „Napisz inaczej”.','Coordinator busy':'Bot jest zajęty inną wysyłką. Spróbuj za chwilę.','Permission revoked or conversation paused':'Rozmowa albo agent jest wstrzymany.','Earlier delivery uncertain; reconcile before sending more':'Poprzednia wysyłka nie jest potwierdzona. Sprawdź rozmowę w Tinderze.','Draft already resolved or unavailable':'Ten szkic jest już wysłany albo odrzucony.'};
const IG_RE=/(?:^|[\s(])(?:ig|insta(?:gram)?)\s*[:\-–]?\s*@?([a-z0-9._]{2,30})/i;
function emptyCard(text){return el('div','rempty',text)}
const ICONS={pause:'<rect x="6" y="4" width="4" height="16" rx="1"/><rect x="14" y="4" width="4" height="16" rx="1"/>',play:'<polygon points="7 4 20 12 7 20 7 4"/>',archive:'<rect x="2" y="3" width="20" height="5" rx="1"/><path d="M4 8v11a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8"/><path d="M10 12h4"/>',trash:'<path d="M3 6h18"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>',bolt:'<polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/>'};
function ico(name){let v=document.createElementNS('http://www.w3.org/2000/svg','svg');v.setAttribute('viewBox','0 0 24 24');v.setAttribute('class','ico');v.setAttribute('aria-hidden','true');v.innerHTML=ICONS[name]||'';return v}
function cbtn(label,icon,cls,fn){let b=el('button','cbtn'+(cls?' '+cls:''));b.type='button';b.append(ico(icon),el('span','',label));b.onclick=fn;return b}
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
let info=el('div','pinfo');if(p.location&&(p.location.city||p.location.distance_km!=null))info.append(el('p','pbio muted',[p.location.city,p.location.distance_km!=null?p.location.distance_km+' km od Ciebie':null].filter(Boolean).join(' · ')));if(p.bio){info.append(el('p','pbio',p.bio));let ig=p.bio.match(IG_RE);if(ig){let a=el('a','igchip','Instagram @'+ig[1]);a.href='https://www.instagram.com/'+encodeURIComponent(ig[1])+'/';a.target='_blank';a.rel='noopener noreferrer';info.append(a)}}
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
function render(){if(!data)return;if(DEEP){DEEP=false;setView('stats')}renderPlanBar();renderOnboarding();renderRoster();if(view==='stats')renderStats();if(view==='auto')renderAuto();
let acct=document.getElementById('account-link'),au=/^https?:\/\//.test(data.account_url||'')?data.account_url:'';acct.hidden=!au;if(au)acct.href=au+'/konto';

const filters=[['all','Wszystkie'],['needs','Do odpowiedzi'],['waiting','Czekają'],['other','Pozostałe']];let fs=document.getElementById('filters');fs.replaceChildren();for(let [value,label] of filters){let b=el('button',value===filter?'active':'',label);b.onclick=()=>{filter=value;render()};fs.append(b)}
let items=data.threads.filter(filtered).sort((a,b)=>tsOf(b)-tsOf(a)||a.display_name.localeCompare(b.display_name));
let list=document.getElementById('threads');list.replaceChildren();if(!items.length)list.append(el('div','empty','Brak rozmów. Nowe dopasowania są na górze, a pojawią się tu po pierwszej wiadomości.'));
for(let t of items){let b=el('button','thread'+(selected===t.id?' selected':''));let top=el('div','row');let nm=el('span','tname');nm.append(avatarFor(t));if(t.queued)nm.append(el('span','qchip','w kolejce'));if(t.state==='needs_reply')nm.append(el('span','dot',''));nm.append(document.createTextNode(t.display_name));top.append(nm,t.plan?planChip(t.plan):el('span','status',statuses[t.state]||t.state));b.append(top,el('div','preview',t.latest_message||'Brak wiadomości'),el('div','mutedline',t.message_count+' wiadomości'+(t.outcomes.length?' • '+t.outcomes.map(k=>OUTCOME_NAMES[k]||k).join(', '):'')));b.onclick=()=>choose(t.id);list.append(b)}
document.getElementById('totals').textContent=data.threads.filter(isConv).length+' rozmów • '+data.threads.filter(t=>t.state==='needs_reply').length+' do odpowiedzi';
let t=threadById();renderProfile(t);if(!t){document.getElementById('title').textContent='Wybierz rozmowę';renderPlan(null);document.getElementById('facts').replaceChildren(emptyCard('Wybierz rozmowę.'));document.getElementById('outcomes').replaceChildren(emptyCard('Wybierz rozmowę.'));return}
document.getElementById('title').textContent=t.display_name+(t.profile?.age?', '+t.profile.age:'');document.getElementById('chatmeta').textContent=(t.profile?.bio||'').slice(0,70)||(t.platform==='tinder'?'Tinder':t.state_reason);document.getElementById('chatavatar').replaceChildren(avatarFor(t,'head'));document.getElementById('chatstatus').textContent=statuses[t.state]||t.state;
let messages=document.getElementById('messages');let keepScroll=messages.scrollTop;messages.replaceChildren();let history=data.messages[t.id]||[];if(!history.length){let hero=el('div','matchhero');let u=safeImg(t.profile?.photos?.[0]);if(u){hero.append(cachedImg('hero:'+t.id,u,'',t.display_name))}else hero.append(avatarFor(t,'hero'));hero.append(el('b','','Dopasowaliście się z '+t.display_name+(t.matched_at?' '+fmtDate(t.matched_at):'')),el('div','','Napisz pierwszą wiadomość sam albo poproś agenta o szkic. Najlepiej zacząć od czegoś z jej opisu.'));messages.append(hero)}else if(t.matched_at)messages.append(el('div','matchline','Dopasowaliście się '+fmtDate(t.matched_at)));
history.forEach((m,i)=>{let b=el('div','bubble'+(m.sender==='you'?' you':''));b.title=m.created_at?new Date(m.created_at).toLocaleString():'';b.append(el('div','',m.body));messages.append(b);if(i===history.length-1&&m.sender==='you')messages.append(el('div','sent','Wysłano'))});if(scrollKey!==t.id+':'+history.length){messages.scrollTop=messages.scrollHeight;scrollKey=t.id+':'+history.length}else messages.scrollTop=keepScroll;
let composer=document.getElementById('composer');composer.replaceChildren();if(t.queued)composer.append(el('div','callout warn','Ta rozmowa czeka w kolejce: pakiet '+data.plan.label+' obsługuje naraz '+data.plan.limit+' aktywnych rozmów. Gdy któraś ucichnie (po '+data.plan.active_days+' dniach bez wiadomości) albo zmienisz pakiet na wyższy, Winq napisze tu szkic.'));let curr=data.drafts.find(d=>d.thread_id===t.id&&d.status==='pending'&&d.anchor_message_id===(t.latest_message_id||OPENER));
let cerr=el('p','cerr');cerr.hidden=true;const fail=e=>{cerr.hidden=false;cerr.textContent=ERR_PL[e.message]||e.message};
const send=async(path,payload,btn)=>{if(btn)btn.disabled=true;cerr.hidden=true;try{await api(path,'POST',payload);await refresh()}catch(e){fail(e);if(btn)btn.disabled=false}};
if((t.state==='needs_reply'||t.state==='new_match')&&curr){let head=el('div','dhead');head.append(el('b','',t.state==='new_match'?'Szkic pierwszej wiadomości':t.automatic_sending?'Autopilot wyśle tę odpowiedź sam':'Szkic odpowiedzi'),el('span','muted','Możesz poprawić tekst przed wysłaniem'));composer.append(head);
 if(!['demo_placeholder','model_error'].includes(curr.generator)){let ta=el('textarea','draftedit');ta.id='draft-edit';ta.value=DRAFT_EDITS.get(curr.id)??curr.body;ta.rows=Math.min(6,Math.max(2,Math.ceil(ta.value.length/60)));ta.maxLength=1000;ta.oninput=()=>DRAFT_EDITS.set(curr.id,ta.value);
  ta.onkeydown=e=>{if(e.key==='Enter'&&(e.metaKey||e.ctrlKey)){e.preventDefault();yes.click()}};composer.append(ta);
  let row=el('div','controls');let yes=el('button','primary','Wyślij');yes.title='Ctrl/Cmd + Enter';yes.onclick=()=>{let body=ta.value.trim();if(!body)return fail({message:'Wiadomość jest pusta.'});send('/api/drafts/'+curr.id+'/approve',body!==curr.body?{body}:undefined,yes).then(()=>DRAFT_EDITS.delete(curr.id))};
  let again=el('button','secondary','Napisz inaczej');again.onclick=()=>{DRAFT_EDITS.delete(curr.id);send('/api/threads/'+encodeURIComponent(t.id)+'/regenerate',undefined,again)};
  let no=el('button','secondary','Odrzuć');no.onclick=()=>{DRAFT_EDITS.delete(curr.id);send('/api/drafts/'+curr.id+'/reject',undefined,no)};row.append(yes,again,no);composer.append(row)}
 else composer.append(el('p','', 'Podłącz model AI w ustawieniach serwera, żeby powstawały pełne szkice.'))}
else if(t.state==='needs_reply'){let rg=data.drafts.find(d=>d.thread_id===t.id&&d.anchor_message_id===t.latest_message_id&&d.status==='regenerate');
 let failed=data.drafts.some(d=>d.thread_id===t.id&&d.anchor_message_id===t.latest_message_id&&['needs_user','no_reply'].includes(d.status));
 if(!data.llm_enabled)composer.append(el('p','','Podłącz model AI, żeby powstawały szkice.'));
 else if(!failed){let w=el('div','working');w.setAttribute('role','status');w.append(el('span','dots'),el('span','',rg?'Piszę nową wersję. Zwykle kilka sekund.':'Szkic się przygotowuje. Pojawi się tu za chwilę.'));composer.append(w)}}
else if(t.state==='new_match'){openerBox(composer,t,send)}
else if(t.state==='waiting'){composer.append(el('p','', 'Ostatnia wiadomość jest Twoja. Czekamy na odpowiedź, bez dopisywania kolejnych.'))}
else composer.append(el('p','',t.state_reason));
composer.append(cerr);
let ctrl=el('div','convbar');
if(['telegram','tinder'].includes(t.platform)){let on=!!t.automatic_sending,grant=cbtn(on?'Autopilot włączony':'Autopilot w tej rozmowie','bolt','ap'+(on?' on':''),()=>showGrant(t));ctrl.append(grant)}
ctrl.append(cbtn(t.user_paused?'Wznów rozmowę':'Wstrzymaj rozmowę',t.user_paused?'play':'pause','',()=>flags(t.id,{paused:!t.user_paused})),cbtn(t.user_archived?'Przywróć z archiwum':'Archiwizuj','archive','',()=>flags(t.id,{archived:!t.user_archived})));
ctrl.append(el('span','cspace'),cbtn('Usuń dane rozmowy','trash','danger',async()=>{if(confirm('Usunąć zapisane dane tej rozmowy? Nie zaimportujemy jej ponownie.')){await api('/api/threads/'+encodeURIComponent(t.id),'DELETE');selected=null;await refresh()}}));
composer.append(ctrl);
let needs=data.drafts.find(d=>d.thread_id===t.id&&d.anchor_message_id===t.latest_message_id&&['needs_user','no_reply'].includes(d.status));if(needs){composer.append(el('p','',(needs.status==='no_reply'?'Winq proponuje nie odpisywać: ':needs.generator==='model_error'?'':'Potrzebna Twoja decyzja: ')+needs.body));
 if(needs.generator==='model_error'){let again=el('button','secondary','Spróbuj ponownie');again.onclick=()=>send('/api/threads/'+encodeURIComponent(t.id)+'/regenerate',undefined,again);composer.append(again)}}
renderPlan(t);let facts=document.getElementById('facts');facts.replaceChildren();const MEM_KIND={question_or_suggestion:'Pytanie lub propozycja',observation:'Obserwacja'},NEXT={review_draft:'Sprawdź szkic odpowiedzi',prepare_draft:'Winq przygotowuje szkic',inspect_profile:'Zerknij na profil',no_action:'Nic do zrobienia'};
const frow=(k,v)=>{if(v===undefined||v===null||v==='')return;let r=el('div','frow');r.append(el('span','fk',k),v instanceof Node?v:el('span','fv',v));facts.append(r)};
frow('Stan',el('span','stchip'+(t.state==='needs_reply'?' hot':''),statuses[t.state]||t.state));frow('Dlaczego',t.state_reason);frow('Wiadomości',t.message_count);frow('Następny krok',NEXT[t.next_action]);if(t.source_visibility&&t.source_visibility!=='available')frow('Dostęp','Niepewny: nie widzimy tej rozmowy w Tinderze');let mem=(data.memory[t.id]||[]).filter(m=>m.value);if(mem.length){facts.append(el('div','fk fmhead','Zapamiętane z rozmowy'));for(let m of mem){let r=el('div','fmem');if(MEM_KIND[m.kind])r.append(el('b','',MEM_KIND[m.kind]));r.append(el('span','',m.value));facts.append(r)}}
let out=document.getElementById('outcomes');out.replaceChildren();let notes=(data.outcome_details[t.id]||[]);if(!notes.length)out.append(emptyCard('Na razie nic. Tu pojawią się potwierdzone ustalenia, np. termin spotkania.'));for(let n of notes){let r=el('div','oc');r.append(el('b','',n.kind),el('div','',n.body));out.append(r)}
updateSystem();
}
async function flags(thread_id,fields){try{await api('/api/threads/'+thread_id+'/flags','POST',fields);await refresh()}catch(e){document.getElementById('status').textContent=e.message}}
async function act(path){try{await api(path,'POST');document.getElementById('status').textContent='';await refresh()}catch(e){document.getElementById('status').textContent=e.message}}
let lastSig='',scrollKey='';
const msgSig=m=>Object.keys(m).map(k=>k+':'+m[k].length+':'+(m[k].length?(m[k][m[k].length-1].id??m[k][m[k].length-1].source_id):'')).join('|');  // messages only ever get appended
function dataSig(d){return JSON.stringify([d.plan,d.campaign,d.threads,msgSig(d.messages),d.drafts,d.grants,msgSig(d.memory),d.settings,d.llm_enabled,d.connections,d.tinder.configured,d.tinder.connections.map(c=>[c.id,c.enabled,c.error,c.auto_send,c.bio_mode,c.bio_disclosure,c.last_sync,c.blocked_until]),{...d.stats,tinder_requests:null}])}
/* Błędy, które mijają same (nasz własny limit zapytań, prośba Tindera o przerwę): bez czerwonego paska, tylko spokojny status przy „Synchronizuj”.
   Pasek na górze pojawia się wyłącznie wtedy, gdy człowiek musi coś zrobić (nowy token, sprawdzenie konta w aplikacji). */
const SOFT_ERRORS=new Set(['rate_limited','server_retry_after','local_request_budget','source_sync_failed']);
function clockText(sec){let d=new Date(sec*1000),t=d.toLocaleTimeString('pl-PL',{hour:'2-digit',minute:'2-digit'});return d.toDateString()===new Date().toDateString()?t:d.toLocaleDateString('pl-PL',{day:'numeric',month:'numeric'})+' '+t}
function agoText(ms){let min=Math.max(0,Math.round((Date.now()-ms)/6e4));return min<1?'przed chwilą':min<60?min+' min temu':min<1440?Math.round(min/60)+' godz. temu':Math.round(min/1440)+' dn. temu'}
function renderConnState(){let box=document.getElementById('syncstate'),al=document.getElementById('account-alert');if(!data||!box)return;
 let c=tinderConn(),ls=c?Date.parse(c.last_sync||''):NaN,blocked=!!(c&&c.enabled&&c.blocked_until>Date.now()/1000),tone='ok',text='',detail='';
 if(!c){tone='off';text='Brak połączenia z Tinderem'}
 else if(data.settings.paused){tone='warn';text='Winq jest wstrzymany';detail='Nic się nie synchronizuje i nic nie wysyła, dopóki go nie wznowisz.'}
 else if(c.error&&!SOFT_ERRORS.has(c.error)){tone='bad';text='Połączenie wymaga uwagi'}
 else if(!c.enabled){tone='warn';text='Synchronizacja wyłączona'}
 else if(blocked){tone='warn';text='Przerwa do '+clockText(c.blocked_until);detail=c.error==='local_request_budget'?'Winq zwalnia tempo zapytań do Tindera, żeby chronić Twoje konto. Wznowi się sam.':'Tinder poprosił o przerwę. Synchronizacja wznowi się sama.'}
 else if(!isNaN(ls))text='Zsynchronizowano '+agoText(ls);
 else{text='Czekamy na pierwszą synchronizację';detail='Pierwszy import może potrwać kilka minut.'}
 if(!isNaN(ls)&&(blocked||data.settings.paused))detail+=(detail?' ':'')+'Ostatnia synchronizacja: '+agoText(ls)+'.';
 box.className='syncstate '+tone;box.replaceChildren(el('i','lsdot'),el('span','sstext',text));if(detail)box.append(el('small','',detail));
 let hard=data.tinder.connections.filter(x=>x.error&&!SOFT_ERRORS.has(x.error));al.hidden=!hard.length;al.replaceChildren();
 if(hard.length){al.append(el('span','',hard.map(x=>tinderErrors[x.error]||'Połączenie z Tinderem wymaga uwagi.').join(' ')));let b=el('button','secondary',hard.some(x=>/token|Sesja|aktualnym/.test(tinderErrors[x.error]||''))?'Podaj nowy token':'Otwórz ustawienia');b.type='button';b.onclick=()=>{setView('settings');showSettings()};al.append(b)}}
function updateSystem(){updateAutopilotButton();renderConnState();let pa=document.getElementById('pause-all');if(pa&&data){let p=!!data.settings.paused;pa.textContent=p?'Wznów Winq':'Wstrzymaj Winq';pa.className=p?'primary':'secondary';pa.title=p?'Winq jest wstrzymany. Kliknij, żeby wznowić synchronizację i automatyczne odpowiedzi.':'Zatrzymuje synchronizację z Tinderem i wszystkie automatyczne odpowiedzi. Wznowisz jednym kliknięciem.'}}
async function refresh(){let next=await api('/api/state');let sig=dataSig(next);data=next;if(!selected||!data.threads.some(t=>t.id===selected)){let c=data.threads.filter(isConv).sort((a,b)=>tsOf(b)-tsOf(a))[0];selected=c?c.id:null}
if(sig===lastSig||document.activeElement?.id==='draft-edit'){updateSystem();return}lastSig=sig;let side=document.getElementById('threads').parentElement,top=side.scrollTop,rost=document.getElementById('roster').scrollLeft;render();side.scrollTop=top;document.getElementById('roster').scrollLeft=rost}
document.getElementById('sync').onclick=async()=>{let b=document.getElementById('sync');b.disabled=true;try{await act('/api/sync')}finally{b.disabled=false}};

function field(label,value,type='text'){let wrap=el('label','fact',label);wrap.style.display='block';let input=el('input','inp');input.type=type;if(type==='checkbox'){input.checked=!!value;input.className=''}else input.value=value;wrap.append(input);return [wrap,input]}
function panel(title){document.getElementById('panel-title').textContent=title;let p=document.getElementById('panel-content');p.replaceChildren();document.getElementById('panel').showModal();return p}
function group(label,desc,control){let g=el('div','group');let l=el('div','glabel',label);g.append(l);if(desc)g.append(el('div','gdesc',desc));g.append(control);return g}
function toggle(label,checked,desc){let w=el('label','switchrow');let t=el('div','');t.append(el('div','glabel',label));if(desc)t.append(el('div','gdesc',desc));let i=el('input','');i.type='checkbox';i.checked=!!checked;let s=el('span','switch');w.append(t,i,s);return [w,i]}
function chip(text,kind){return el('span','chip '+kind,text)}
const tinderErrors={inbox_access_denied:'Tinder odrzucił dostęp do skrzynki (401). Połącz ponownie z aktualnym tokenem.',session_expired_or_account_changed:'Sesja wygasła albo zmieniło się konto. Podaj nowy token.',session_expired_or_access_denied:'Sesja wygasła. Podaj nowy token.',restriction_requires_manual_review:'Tinder wymaga sprawdzenia konta w oficjalnej aplikacji.',rate_limited:'Tinder poprosił o przerwę. Synchronizacja wznowi się sama.',server_retry_after:'Tinder poprosił o przerwę. Synchronizacja wznowi się sama.',local_request_budget:'Osiągnięto lokalny limit zapytań. Synchronizacja wznowi się sama.',source_sync_failed:'Ostatnia synchronizacja się nie udała. Spróbuje ponownie.',circuit_open_requires_review:'Zbyt wiele błędów z rzędu. Sprawdź połączenie i połącz ponownie.',repeated_rate_limits_requires_review:'Wielokrotne ograniczenia od Tinder. Poczekaj przed ponownym połączeniem.'};
const STYLE_PRESETS=[
 ['Luźno i krótko','krótko, zwykle około 30 znaków, jedno-dwa zdania, od małej litery, bez emoji, pytanie tylko gdy naturalne, bez serii pytań, reaguj konkretnie na to, co napisała, lekki humor, bez komplementów na siłę'],
 ['Ciepło i z humorem','ciepło i z humorem, jedno-dwa zdania, lekki żart albo ironia, czasem emoji, ale nie w każdej wiadomości, dopytuj o to, co ją naprawdę zaciekawiło, bez komplementów na siłę'],
 ['Pewnie i konkretnie','pewnie i konkretnie, krótkie zdania, bez owijania w bawełnę, bez przeprosin i bez nadmiaru emoji, prowadź rozmowę do konkretu, ale bez nacisku'],
 ['Spokojnie i uprzejmie','spokojnie i uprzejmie, pełne zdania i poprawna interpunkcja, bez slangu, ciepły ton, bez presji, bez emoji poza uśmiechem od czasu do czasu']];
const FACTS=[['imię','Imię','np. Kuba'],['wiek','Wiek','np. 29'],['miasto','Miasto','np. Warszawa'],['praca lub studia','Praca lub studia','np. projektuję aplikacje'],['zainteresowania','Zainteresowania','np. bieganie, kuchnia azjatycka, planszówki'],['co lubię robić na randce','Idealna pierwsza randka','np. kawa i spacer']];
function showSettings(tab='general'){setView('settings');let p=document.getElementById('settings-view');p.replaceChildren();let cfg=data.settings;let result=el('div','mresult');
let tabs=[['general','Ogólne','Jak Winq pracuje, w jakim języku pisze i jak długo trzyma rozmowy.'],['goal','Cel i spotkania','Dokąd Winq prowadzi rozmowę, jak szybko proponuje spotkanie i kiedy masz czas.'],['style','Styl i o Tobie','Jak brzmisz i co Winq może o Tobie mówić. Zmiany działają od razu, także na szkice, które już czekają.'],['tinder','Tinder','Połączenie konta, token i pełny import historii.'],['accounts','Konto','Wylogowanie, konto Winq i połączone konta.']];let shell=el('div','sv');let bar=el('nav','sv-nav');bar.setAttribute('aria-label','Sekcje ustawień');let main=el('div','sv-main');let head=el('div','sv-head');let body=el('div','sect');main.append(head,body);
// Changes save themselves: selects and switches at once, text when you leave the field or switch section.
let timer=null;const queue=ms=>{clearTimeout(timer);result.className='mresult';result.textContent='Zapisuję…';timer=setTimeout(()=>{timer=null;saveSettings()},ms)};
const flush=async()=>{if(timer){clearTimeout(timer);timer=null;await saveSettings()}};
body.addEventListener('change',e=>{if(['general','goal','style'].includes(tab)&&!e.target.closest('.nosave'))queue(200)});
body.addEventListener('input',e=>{if(['general','goal','style'].includes(tab)&&e.target.matches('textarea,input:not([type=checkbox])')){result.className='mresult';result.textContent='Zapisze się, gdy klikniesz poza pole.'}});shell.append(bar,main);p.append(shell);
let fields={};
function build(){bar.replaceChildren();bar.append(el('div','sv-title','Ustawienia'));for(let [k,l] of tabs){let b=el('button','sv-item'+(tab===k?' active':''),l);b.onclick=async()=>{await flush();tab=k;build()};bar.append(b)}let cur=tabs.find(x=>x[0]===tab)||tabs[0];head.replaceChildren(el('h2','',cur[1]),el('p','',cur[2]));if(['general','goal','style'].includes(tab))head.append(result);body.replaceChildren();result.className='mresult';result.textContent=['general','goal','style'].includes(tab)?'Zmiany zapisują się same.':'';fields={};
if(tab==='general'){
 let mode=el('select','inp');for(let [v,l] of [['supervised','Normalny: Winq pisze szkice, Ty klikasz Wyślij'],['simulation','Test: tylko fikcyjne rozmowy'],['authorized_autonomy','Autopilot także poza Tinderem (np. Telegram)']]){let o=el('option','',l);o.value=v;o.selected=cfg.mode===v;mode.append(o)}fields.mode=mode;
 let modeGroup=group('Tryb pracy','Zostaw „Normalny”. Autopilota na Tinderze włączasz przyciskiem „Autopilot” u góry strony.',mode);
 let lang=el('select','inp');let langs=[['auto','Taki jak rozmówczyni (zalecane)'],['pl','Zawsze polski'],['en','Zawsze angielski']];if(!langs.some(x=>x[0]===cfg.language))langs.push([cfg.language,cfg.language]);for(let [v,l] of langs){let o=el('option','',l);o.value=v;o.selected=cfg.language===v;lang.append(o)}fields.language=lang;body.append(group('Język odpowiedzi','Z opcją zalecaną Winq odpisuje w języku, w którym napisała ona.',lang));
 let ret=el('input','inp');ret.type='number';ret.min=1;ret.max=365;ret.value=cfg.retention_days;fields.retention_days=ret;body.append(group('Jak długo trzymamy rozmowy (dni)','Rozmowy, w których od tylu dni nie ma żadnej wiadomości, są usuwane automatycznie. Maksimum 365.',ret));
 let [w,em]=toggle('Powiadomienia e-mail',cfg.email,'Wiadomość na e-mail, gdy pojawi się szkic do zatwierdzenia albo ustalicie spotkanie.');fields.email=em;body.append(w);
 let adv=el('details','advanced');adv.append(el('summary','','Zaawansowane'),modeGroup);body.append(adv);}
if(tab==='goal'){

 let goal=el('select','inp');for(let [v,l] of [['date','Spotkanie na żywo (Instagram jako plan B)'],['date_or_instagram','Spotkanie albo Instagram'],['instagram','Instagram'],['chat','Tylko rozmowa, bez zaproszeń']]){let o=el('option','',l);o.value=v;o.selected=(cfg.goal||'date')===v;goal.append(o)}fields.goal=goal;body.append(group('Cel','Bot prowadzi rozmowę w stronę tego celu, ale odmowa lub wahanie zawsze wygrywa.',goal));
 let pace=el('select','inp');for(let [v,l] of [['slow','Spokojne: zaproszenie po ok. 7 wymianach'],['normal','Normalne: po ok. 5 wymianach'],['fast','Szybkie: po ok. 3 wymianach']]){let o=el('option','',l);o.value=v;o.selected=(cfg.pace||'normal')===v;pace.append(o)}fields.pace=pace;body.append(group('Tempo','Tylko gdy widać zainteresowanie. Jeśli sama wspomni o wyjściu, bot zaproponuje wcześniej.',pace));
 let [iw,ig]=toggle('Instagram jako lżejszy krok',cfg.allow_instagram!==false,'Gdy odłoży spotkanie na „kiedyś", a rozmowa jest ciepła.');fields.allow_instagram=ig;body.append(iw);
 let av=el('input','inp');av.value=cfg.availability||'';fields.availability=av;body.append(group('Kiedy masz czas','Bot proponuje terminy tylko z tego opisu.',av));
 let ideas=el('textarea','inp');ideas.rows=5;ideas.value=(cfg.date_ideas&&cfg.date_ideas.length?cfg.date_ideas:['kawa albo matcha na mieście','spacer z kawą na wynos','piwo albo wino w luźnym barze','wystawa, targi albo coś w tym stylu','planszówki w barze','lody albo gofry i spacer']).join('\n');fields.date_ideas=ideas;body.append(group('Pomysły na pierwsze spotkanie','Jeden pomysł w linii. Bot dobiera ten, który pasuje do Waszej rozmowy.',ideas));}
if(tab==='style'){
 let lib=el('div','measured');lib.append(el('div','gdesc','Sprawdzam, jak piszesz na Tinderze…'));
 let style=el('textarea','inp');style.rows=4;style.maxLength=1000;style.value=cfg.style;fields.style=style;
 let mark=()=>{for(let b of presets.children)b.classList.toggle('on',STYLE_PRESETS.some(x=>x[0]===b.textContent&&x[1]===style.value))};
 let presets=el('div','presets');for(let [name,text] of STYLE_PRESETS){let b=el('button','chipbtn',name);b.type='button';b.onclick=()=>{style.value=text;mark();queue(0)};presets.append(b)}style.oninput=mark;mark();
 api('/api/style').then(r=>{lib.replaceChildren();if(r.stats.based_on!=='own_messages'){lib.append(el('div','gdesc','Gdy wyślesz na Tinderze ok. 15 odpowiedzi, Winq zmierzy Twój prawdziwy styl i zaproponuje opis.'));return}
 lib.append(el('div','gdesc','Twoje odpowiedzi na Tinderze ('+r.own_pairs+'): zwykle '+r.stats.median_chars+' znaków, '+r.stats.lowercase_start_pct+'% od małej litery, '+r.stats.question_pct+'% kończy się pytaniem, emoji w '+r.stats.emoji_pct+'%.'));
 let use=el('button','secondary','Użyj stylu z moich wiadomości');use.type='button';use.onclick=()=>{style.value=r.suggested_style;mark();queue(0)};lib.append(use)}).catch(()=>{lib.replaceChildren(el('div','gdesc','Nie udało się zmierzyć stylu z Twoich wiadomości. To nie przeszkadza: wybierz styl powyżej.'))});
 let sw=el('div','');sw.append(presets,style,lib);body.append(group('Jak piszesz','Kliknij gotowy styl albo opisz własnymi słowami: długość, humor, emoji, wielkość liter. Zapisuje się od razu i działa też na szkice, które już czekają.',sw));
 let profile=cfg.profile||{};let known=new Set(FACTS.map(f=>f[0]));fields.facts=[];fields.extra=[];
 let fl=el('div','factform');for(let [k,l,ph] of FACTS){let [fw,fi]=field(l,profile[k]||'');fi.placeholder=ph;fi.maxLength=300;fields.facts.push([k,fi]);fl.append(fw)}
 let extra=el('div','extrafacts');const addRow=(k,v)=>{let r=el('div','kvrow');let ki=el('input','inp');ki.placeholder='Co (np. pies)';ki.value=k;ki.maxLength=60;let vi=el('input','inp');vi.placeholder='Fakt (np. mam labradora Burka)';vi.value=v;vi.maxLength=300;r.append(ki,vi);extra.append(r);fields.extra.push([ki,vi])};
 for(let k of Object.keys(profile).filter(k=>!known.has(k)))addRow(k,profile[k]);
 let add=el('button','secondary','Dodaj własny fakt');add.type='button';add.onclick=()=>addRow('','');
 let pull=el('button','secondary','Pobierz zainteresowania z Tindera');pull.type='button';const tc=tinderConn();if(!tc)pull.disabled=true;
 let pres=el('div','mresult');pull.onclick=async()=>{pull.disabled=true;pres.className='mresult';pres.textContent='Czytam Twój profil na Tinderze…';
  try{const r=await api('/api/tinder/connections/'+encodeURIComponent(tc.id)+'/sync-profile','POST');await refresh();cfg=data.settings;
   if(r.filled){showSettings('style')}else{pres.className='mresult ok';pres.textContent=r.interests.length?'Masz już wpisane zainteresowania, więc ich nie zmieniam. Na Tinderze: '+r.interests.join(', '):'Nie widzę zainteresowań w Twoim profilu na Tinderze.';pull.disabled=false}}
  catch(e){pres.className='mresult err';pres.textContent=ERR_PL[e.message]||e.message;pull.disabled=false}};
 let fwrap=el('div','');fwrap.append(fl,pull,pres,extra,add);body.append(group('Fakty o Tobie','Tylko to, co sam tu wpiszesz, Winq może powiedzieć o Tobie. Niczego nie dopisuje ze starych wiadomości. Im więcej prawdziwych szczegółów, tym mniej odpowiedzi „do sprawdzenia”.',fwrap));
 let fb=el('textarea','inp');fb.rows=4;fb.placeholder='np. Nigdy nie używaj wykrzykników\nNie pytaj o pracę w pierwszych wiadomościach';fb.value=cfg.feedback.join('\n');fields.feedback=fb;body.append(group('Twoje zasady','Jedna zasada w linii. Winq przestrzega ich w każdej wiadomości.',fb));}
if(tab==='tinder')buildTinder();
if(tab==='accounts'){
 let me=el('div','scard');me.append(el('div','glabel','Sesja'),el('div','gdesc','Wylogowanie kończy sesję w tej przeglądarce. Bot dalej działa w tle zgodnie z ustawieniami.'));let row=el('div','btnrow');let lo=el('button','secondary','Wyloguj się');lo.onclick=logoutNow;row.append(lo);if(data.account_url){let ac=el('a','secondary','Konto Winq');ac.href=data.account_url+'/konto';row.append(ac)}me.append(row);body.append(me);
 body.append(el('div','glabel','Połączone konta'),el('div','gdesc','Odwołanie połączenia zatrzymuje agenta dla tego konta. Dane rozmów zostają, dopóki ich nie usuniesz.'));
 if(!data.connections.length)body.append(el('div','empty','Brak połączonych kont.'));
 for(let c of data.connections){let row=el('div','acct');row.append(el('div','acctname',c.id),chip(c.enabled?'aktywne':'wyłączone',c.enabled?'ok':'warn'));let b=el('button','secondary danger','Odwołaj');b.onclick=async()=>{if(!confirm('Odwołać połączenie '+c.id+'?'))return;await api('/api/connections/'+encodeURIComponent(c.id)+'/revoke','POST');await refresh();showSettings('accounts')};row.append(b);body.append(row)}
 if(data.account_url){let adv=el('a','gdesc',' Zaawansowane ustawienia konta');adv.href=data.account_url+'/konto/zaawansowane';adv.style.cssText='display:block;margin-top:56px;font-size:12px;opacity:.55';body.append(adv)}}}
async function saveSettings(){try{let next={...cfg};const v=k=>fields[k];
 if(v('mode'))next.mode=v('mode').value;if(v('language'))next.language=v('language').value.trim();if(v('retention_days'))next.retention_days=Number(v('retention_days').value);if(v('email'))next.email=v('email').checked;
 if(v('goal'))next.goal=v('goal').value;if(v('pace'))next.pace=v('pace').value;if(v('allow_instagram'))next.allow_instagram=v('allow_instagram').checked;if(v('availability'))next.availability=v('availability').value.trim();if(v('date_ideas'))next.date_ideas=v('date_ideas').value.split('\n').map(x=>x.trim()).filter(Boolean);
 if(v('style'))next.style=v('style').value.trim();if(v('feedback'))next.feedback=v('feedback').value.split('\n').map(x=>x.trim()).filter(Boolean);
 if(v('facts')){let pr={};for(let [k,i] of v('facts')){let x=i.value.trim();if(x)pr[k]=x}for(let [ki,vi] of v('extra')){let k=ki.value.trim(),x=vi.value.trim();if(k&&x)pr[k]=x}next.profile=pr}
 let r=await api('/api/settings','PUT',next);await refresh();cfg=data.settings;result.className='mresult ok';result.textContent=r.regenerating?'Zapisano ✓ Przepisuję '+r.regenerating+(r.regenerating===1?' czekający szkic':' czekających szkiców')+' w nowym stylu. Zobaczysz je za chwilę.':'Zapisano ✓'}catch(e){result.className='mresult err';result.textContent=ERR_PL[e.message]||e.message}}
function buildTinder(){
 let cons=data.tinder.connections;let ts=data.tinder;
 let tok=el('div','scard');tok.append(el('div','glabel','Token Tindera'));
 if(ts.token_source){let row=el('div','row');row.append(el('div','gdesc',(ts.token_source==='vault'?'Zapisany w tym panelu, zaszyfrowany (AES-256).':'Ustawiony przez administratora serwera.')+' Odcisk: …'+(ts.token_fingerprint||'')),chip('zapisany','ok'));tok.append(row);
  if(ts.token_source==='vault'){let del=el('button','secondary danger','Usuń token i rozłącz');del.onclick=async()=>{if(!confirm('Usunąć token? Bot przestanie synchronizować i wysyłać.'))return;await api('/api/tinder/token','DELETE');await refresh();showSettings('tinder')};tok.append(del)}}
 else tok.append(el('div','gdesc','Brak tokena. Wklej go poniżej, żeby połączyć konto.'));
 if(!ts.enabled)tok.append(el('div','callout warn','Integracja Tinder jest wyłączona na tym serwerze (TINDER_ENABLED).'));
 if(!ts.vault_ready&&ts.token_source!=='env')tok.append(el('div','callout warn','Serwer nie ma klucza szyfrowania, więc nie zapisze tokena. Skontaktuj się z obsługą.'));


 let how=el('details','howto');how.append(el('summary','','Jak zdobyć token? Krok po kroku (ok. 2 minuty)'));
 how.append(el('div','gdesc','Token to długi „kod dostępu” do Twojego konta na Tinderze. Nie musisz go rozumieć, wystarczy go skopiować z przeglądarki i wkleić tutaj. Niczego nie psujesz i niczego nie zmieniasz, tylko patrzysz i kopiujesz. Potrzebny jest komputer (nie telefon) oraz przeglądarka Chrome albo Safari.'));
 let appleLink=()=>{let a=el('a','','oficjalna instrukcja Apple');a.href='https://support.apple.com/pl-pl/guide/safari/sfri20948/mac';a.target='_blank';a.rel='noopener noreferrer';return a};
 let steps=[
  ['Wejdź na Tindera w przeglądarce',['Na komputerze otwórz stronę tinder.com i zaloguj się tak jak zwykle (numerem telefonu, Facebookiem albo Google). Zostaw tę kartę otwartą.']],
  ['Tylko Safari: najpierw włącz ukrytą funkcję',['Safari domyślnie ukrywa narzędzia, których potrzebujemy, więc trzeba je raz włączyć. Chrome: pomiń ten krok. W Safari zrób tak: 1) na samej górze ekranu, w pasku z menu, kliknij „Safari”; 2) wybierz „Ustawienia…”; 3) kliknij zakładkę „Zaawansowane” (ostatnia z prawej); 4) na samym dole zaznacz ptaszkiem „Pokaż funkcje dla deweloperów www”; 5) zamknij okno ustawień. Gotowe, robisz to tylko raz. Jeśli coś się nie zgadza, tu jest ',appleLink,' (po polsku, z opisem).']],
  ['Otwórz „narzędzia deweloperskie”',['To ukryty panel z technicznymi informacjami o stronie. Najprościej: kliknij PRAWYM przyciskiem myszy w puste miejsce na stronie Tindera (nie na zdjęciu ani przycisku) i z listy wybierz „Zbadaj” (Chrome) albo „Zbadaj element” (Safari). Nie masz prawego przycisku? Na gładziku Maca kliknij dwoma palcami naraz (albo przytrzymaj klawisz Ctrl i kliknij). Możesz też użyć skrótu: F12 (Windows, Chrome) albo Cmd+Opcja+I (Mac, Chrome i Safari). Obok strony otworzy się panel z kodem. Niczego w nim nie zmieniaj, wystarczy, że go otworzysz.']],
  ['Znajdź zakładkę z zapisanymi danymi',['U góry panelu jest rząd zakładek (Elements, Console, Network…). W Chrome kliknij „Application”. W Safari kliknij „Pamięć” (po angielsku „Storage”, ikona małej szuflady). Jeśli zakładki nie widać, kliknij strzałkę „»” na końcu rzędu, tam się chowa.']],
  ['Otwórz Local Storage',['W lewej kolumnie panelu znajdź „Local Storage” (w Safari może być „Pamięć lokalna”). Kliknij strzałkę obok, żeby go rozwinąć, i kliknij „https://tinder.com”. Po prawej pojawi się tabelka z dwiema kolumnami: Key (nazwa) i Value (wartość).']],
  ['Znajdź właściwy wiersz',['Szukaj w kolumnie Key wiersza o nazwie TinderWeb/APIToken. Tabelka jest długa, więc użyj pola „Filter” nad nią i wpisz APIToken. Zostanie jeden wiersz. Nie ma pola Filter? Przewijaj tabelkę, aż trafisz na tę nazwę.']],
  ['Skopiuj wartość',['Kliknij ten wiersz. W kolumnie Value jest ciąg liter, cyfr i myślników, wygląda mniej więcej tak: 1a2b3c4d-5e6f-7a8b-9c0d-1e2f3a4b5c6d (ma 36 znaków). Kliknij dwa razy w tę wartość, zaznacz ją całą i skopiuj: Ctrl+C (Windows) albo Cmd+C (Mac). W Chrome pełna wartość pokazuje się też na dole panelu po kliknięciu wiersza.']],
  ['Wklej tutaj',['Wróć do tej strony i kliknij pole „Wklej token” poniżej. Wklej: Ctrl+V albo Cmd+V. Zaznacz trzy zgody i kliknij „Zapisz i połącz”. Jeśli się uda, zobaczysz zielone „zapisany”.']]
 ];
 steps.forEach((st,i)=>{let r=el('div','sig');r.append(el('b','',(i+1)+'. '+st[0]+'. '));for(let part of st[1])r.append(typeof part==='string'?document.createTextNode(part):part());r.style.marginBottom='10px';how.append(r)});
 how.append(el('div','callout warn','Token działa jak hasło do Twojego konta. Nie wysyłaj go nikomu, nie wklejaj w czatach ani na forach i nie podawaj osobom, które o niego proszą. Tutaj zapisujemy go zaszyfrowanego. Jeśli po jakimś czasie przestanie działać (np. po wylogowaniu z tinder.com), po prostu powtórz te kroki i wklej nowy.'));
 tok.append(how);
 let tin=el('input','inp');tin.type='password';tin.autocomplete='off';tin.placeholder=ts.token_source?'Wklej nowy token, żeby go podmienić':'Wklej token';tin.spellcheck=false;
 let [tow,town]=toggle('To jest moje konto Tinder',false);let [tak,tack]=toggle('Rozumiem, że integracja jest nieoficjalna i Tinder może ograniczyć konto',false);let [tsd,tsdc]=toggle('Zgadzam się na przetwarzanie danych z rozmów, które mogą dotyczyć życia intymnego (art. 9 RODO). Zgodę wycofam, usuwając token.',false);
 let tres=el('div','mresult');let tsave=el('button','primary','Zapisz i połącz');tsave.disabled=!ts.enabled||!ts.vault_ready;
 tsave.onclick=async()=>{tsave.disabled=true;tres.className='mresult';tres.textContent='Sprawdzam token w Tinderze...';try{await api('/api/tinder/token','POST',{token:tin.value,account_owned:town.checked,acknowledge_unofficial:tack.checked,sensitive_data:tsdc.checked});tin.value='';await refresh();showSettings('tinder')}catch(e){tres.className='mresult err';tres.textContent=e.message;tsave.disabled=false}finally{tin.value=''}};
 tok.append(tin,tow,tak,tsd,tsave,tres);body.append(tok);
 for(let c of cons){let card=el('div','scard');let top=el('div','row');top.append(el('b','',c.id.replace('tinder:','Konto ').slice(0,28)+'…'),chip(c.enabled&&!c.error?'połączone':c.error?'wstrzymane':'wyłączone',c.enabled&&!c.error?'ok':c.error?'err':'warn'));card.append(top);
  card.append(el('div','gdesc','Ostatnia synchronizacja: '+(c.last_sync?new Date(c.last_sync).toLocaleString():'jeszcze nie było')));
  if(c.error)card.append(el('div','callout err',tinderErrors[c.error]||('Wymaga uwagi: '+c.error)));
  card.append(autopilotCard(c,()=>showSettings('tinder')));body.append(card)}
 let load=el('div','scard');load.append(el('div','glabel','Pełny import historii'),el('div','gdesc','Pobiera w tle wszystkie dopasowania, rozmowy i zdjęcia, także te usunięte wcześniej przez retencję. Trwa od kilku do kilkunastu minut, na wyższych limitach jednorazowo; potem bot wraca do zwykłych limitów. Zwykłe odświeżanie robi przycisk Synchronizuj na liście rozmów.'));let note=el('div','mresult');let lb=el('button','primary','Uruchom pełny import');lb.disabled=!data.tinder.configured;lb.onclick=async()=>{lb.disabled=true;try{let r=await api('/api/tinder/restore-deleted','POST');note.className='mresult ok';note.textContent='Import ruszył w tle (odblokowano rozmów: '+r.restored+'). Rozmowy będą się pojawiać stopniowo. Koniec importu zobaczysz w Aktywności jako tinder_initial_import_done.';setTimeout(()=>refresh().catch(()=>{}),15000)}catch(e){note.className='mresult err';note.textContent=e.message}finally{lb.disabled=false}};load.append(lb,note);body.append(load);
 if(!data.tinder.configured)return;let conn=el('div','scard');conn.append(el('div','glabel',cons.length?'Połącz ponownie':'Połącz konto Tinder'),el('div','gdesc','Połączenie włącza automatyczne odpowiedzi tylko dla tego konta Tinder, w rozmowach ze zgodą i ujawnieniem. Integracja jest nieoficjalna i Tinder może ograniczyć konto.'));
 let [ow,owned]=toggle('To jest moje konto',false);let [aw,ack]=toggle('Rozumiem, że integracja jest nieoficjalna',false);let cres=el('div','mresult');let cb=el('button','primary',cons.length?'Połącz ponownie':'Połącz Tinder');cb.disabled=!data.tinder.configured;
 cb.onclick=async()=>{cb.disabled=true;try{await api('/api/tinder/connect','POST',{account_owned:owned.checked,acknowledge_unofficial:ack.checked});await refresh();showSettings('tinder')}catch(e){cres.className='mresult err';cres.textContent=e.message;cb.disabled=false}};conn.append(ow,aw,cb,cres);body.append(conn)}
build()}
function tinderConn(){return (data.tinder.connections||[])[0]}
function apLive(c){return !!(c&&c.auto_send&&c.bio_mode&&c.bio_disclosure)}
function updateAutopilotButton(){let b=document.getElementById('autopilot-btn');if(!b||!data)return;let c=tinderConn(),live=apLive(c),wait=!live&&!!(c&&c.auto_send);b.replaceChildren(el('span','apdot'+(live?' on':wait?' wait':'')),document.createTextNode(live?'Autopilot: włączony':wait?'Autopilot: czeka na bio':'Autopilot: wyłączony'))}
function upgradeLink(text){const a=el('a','secondary',text);a.href=(data.account_url||'')+'/konto#pakiety';return a}
function renderPlanBar(){const box=document.getElementById('plan-bar');if(!box)return;const p=data.plan;if(!p){box.hidden=true;return}
 box.hidden=false;box.replaceChildren();const top=el('div','plan-top');
 top.append(el('b','','Pakiet '+p.label),el('span','muted',p.used+' z '+p.limit+' aktywnych rozmów'));
 if(p.queued)top.append(el('span','plan-wait',p.queued+(p.queued===1?' rozmowa czeka w kolejce':' rozmowy czekają w kolejce')));
 if(p.used>=p.limit||p.queued)top.append(upgradeLink('Zmień pakiet'));
 const bar=el('div','plan-meter'),fill=el('span');fill.style.width=Math.min(100,Math.round(100*p.used/Math.max(1,p.limit)))+'%';if(p.used>=p.limit)fill.className='full';bar.append(fill);box.append(top,bar)}
function closePanel(){const d=document.getElementById('panel');if(d.open)d.close()}
let bioSeen=null,guideNote=null;
function startGuide(after){const t=data.tinder||{},c=tinderConn(),cfg=data.settings,live=apLive(c);
 const box=el('div','guide'),msg=el('div','mresult'+(guideNote?' '+guideNote[0]:''),guideNote?guideNote[1]:'');
 const step=(n,state,title,desc,...controls)=>{const s=el('div','gstep '+state);s.append(el('span','gnum',state==='done'?'✓':String(n)));const tx=el('div','gtxt');tx.append(el('b','',title));if(desc)tx.append(el('div','gdesc',desc));if(controls.length){const r=el('div','gctl');r.append(...controls);tx.append(r)}s.append(tx);box.append(s)};
 const fail=e=>{guideNote=['err',ERR_PL[e.message]||e.message];msg.className='mresult err';msg.textContent=guideNote[1]};
 const setAuto=async(patch,wait)=>{guideNote=null;msg.className='mresult';msg.textContent=wait;
  try{await api('/api/tinder/connections/'+encodeURIComponent(c.id)+'/automation','PUT',patch);if(patch.bio_mode)await checkBio(true);await refresh();after()}catch(e){fail(e);await refresh().catch(()=>{});after()}};
 const checkBio=async quiet=>{guideNote=null;msg.className='mresult';msg.textContent='Sprawdzam Twoje bio na Tinderze…';try{const r=await api('/api/tinder/connections/'+encodeURIComponent(c.id)+'/check-bio','POST');bioSeen=r;if(!quiet){await refresh();after()}}catch(e){fail(e);if(quiet)throw e}};
 if(!data.llm_enabled)box.append(el('div','callout warn','Na serwerze brakuje klucza modelu AI, więc Winq nie napisze odpowiedzi. Daj znać obsłudze.'));
 if(t.enabled===false)box.append(el('div','callout warn','Połączenie z Tinderem jest wyłączone na tym serwerze. Daj znać obsłudze.'));
 // 1. Tinder
 if(c)step(1,'done','Konto Tinder połączone',c.error?(tinderErrors[c.error]||'Połączenie wymaga uwagi.'):'');
 else{const b=el('button','primary','Połącz Tinder');b.onclick=()=>{closePanel();showSettings('tinder')};step(1,'now','Połącz konto Tinder','Wklejasz token z tinder.com w Ustawieniach. Instrukcja jest przy polu, to ok. 2 minuty.',b)}
 // 2. Style: one click, saved at once
 const chips=el('div','presets');const cur=STYLE_PRESETS.find(x=>x[1]===cfg.style);
 for(const [name,text] of STYLE_PRESETS){const b=el('button','chipbtn'+(cfg.style===text?' on':''),name);b.type='button';
  b.onclick=async()=>{for(const x of chips.children)x.disabled=true;msg.className='mresult';msg.textContent='Zapisuję styl…';
   try{await api('/api/settings','PUT',{...data.settings,style:text});await refresh();after()}catch(e){fail(e);for(const x of chips.children)x.disabled=false}};chips.append(b)}
 const more=el('button','linkish','Fakty o Tobie i własne zasady →');more.type='button';more.onclick=()=>{closePanel();showSettings('style')};
 step(2,'done','Styl: '+(cur?cur[0]:'Twój własny opis'),'Kliknij inny, jeśli chcesz. Zapisuje się od razu.',chips,more);
 // 3. Bio disclosure
 if(!c)step(3,'todo','Dopisz „AI” do bio na Tinderze','Najpierw połącz konto.');
 else if(c.bio_mode&&c.bio_disclosure){const off=el('button','linkish','Usunąłem to z bio');off.type='button';off.onclick=()=>setAuto({bio_mode:false},'Zapisuję…');step(3,'done','„AI” jest w Twoim bio','Sprawdzamy to przy każdej synchronizacji. Jeśli zniknie, autopilot się zatrzyma.',off)}
 else{const ex=el('button','bioex','Używam AI czasami, a ty? 🤖');ex.type='button';ex.title='Kliknij, żeby skopiować';
  ex.onclick=()=>{navigator.clipboard?.writeText(ex.textContent).then(()=>{msg.className='mresult ok';msg.textContent='Skopiowane. Wklej w aplikacji Tinder: Profil → Edytuj → O mnie.'}).catch(()=>{})};
  const done=el('button','primary',c.bio_mode?'Sprawdź ponownie':'Dodałem, sprawdź');
  done.onclick=()=>c.bio_mode?checkBio(false):setAuto({bio_mode:true},'Sprawdzam Twoje bio na Tinderze…');
  step(3,'now','Dopisz „AI” do bio na Tinderze',c.bio_mode?(bioSeen&&!bioSeen.found?(bioSeen.bio?'Sprawdziliśmy przed chwilą. Twoje bio na Tinderze to teraz: „'+bioSeen.bio.slice(0,200)+(bioSeen.bio.length>200?'…':'')+'”. Brakuje w nim słowa „AI”. Dopisz np. zdanie poniżej, zapisz profil w aplikacji i kliknij „Sprawdź ponownie”.':'Sprawdziliśmy przed chwilą: Twoje bio na Tinderze jest puste. Dopisz zdanie poniżej, zapisz profil w aplikacji i kliknij „Sprawdź ponownie”.'):'Nie widzimy jeszcze słowa „AI” w Twoim bio. Zapisz bio w aplikacji i kliknij „Sprawdź ponownie”.'):'Osoby, z którymi piszesz, mają wiedzieć, że pomaga Ci asystent. Dodaj w aplikacji Tinder (Profil → Edytuj → O mnie) zdanie ze słowem „AI”, np.:',ex,done)}
 // 4. Switch on
 if(data.plan&&!data.plan.autopilot)step(4,'todo','Autopilot jest w pakietach Flirt i Casanova','Pakiet '+data.plan.label+' pisze szkice, a Ty klikasz „Wyślij”. Autopilot odpisuje sam od pakietu Flirt.',upgradeLink('Zobacz pakiety'));
 else if(!c)step(4,'todo','Włącz autopilota','Najpierw połącz konto.');
 else if(live){const b=el('button','secondary','Wyłącz autopilota');b.onclick=()=>setAuto({enabled:false},'Wyłączam…');step(4,'done','Autopilot działa','Winq sam odpisuje, gdy ktoś Ci napisze. Pierwszą wiadomość do nowej pary piszesz Ty.',b)}
 else if(c.auto_send){const b=el('button','secondary','Wyłącz autopilota');b.onclick=()=>setAuto({enabled:false},'Wyłączam…');step(4,'wait','Autopilot włączony, czeka na krok 3','Zacznie odpisywać, gdy zobaczymy „AI” w Twoim bio.',b)}
 else{const b=el('button','primary big','Włącz autopilota');b.onclick=()=>setAuto({enabled:true},'Włączam…');step(4,'now','Włącz autopilota','Winq będzie sam odpisywać w rozmowach, w których ktoś Ci napisał.',b)}
 box.append(msg);
 const safe=el('details','howto');safe.append(el('summary','','Jakie są zabezpieczenia?'),el('div','gdesc','Jeśli ktoś zapyta o bota, Winq odpowie szczerze, że czasem pomaga Ci AI. Jeśli ktoś się sprzeciwi, rozmowa wraca do Ciebie. Bot nie dopisuje kolejnych wiadomości, gdy ostatnia jest Twoja. Jedną rozmowę wyłączysz pod czatem („Autopilot w tej rozmowie”), wszystko naraz przyciskiem „Wstrzymaj Winq”.'));box.append(safe);
 return box}
function autopilotCard(c,after){return startGuide(after)}
function showAutopilot(){fillAutopilot(panel('Autopilot'))}
function fillAutopilot(p){p.replaceChildren();
 p.append(startGuide(()=>fillAutopilot(document.getElementById('panel-content'))))}
function showGrant(t){let p=panel('Autopilot: '+t.display_name);let old=data.grants.find(g=>g.thread_id===t.id);let conn=data.tinder.connections.find(c=>c.id===t.connection_id)||{};
let bioOn=t.platform==='tinder'&&conn.auto_send&&conn.bio_mode&&conn.bio_disclosure;
if(bioOn){let off=old&&!old.enabled;p.append(el('p','',off?'Autopilot jest w tej rozmowie wyłączony'+(old.participant_consent===0&&old.disclosed===0?' (np. zapytała o AI albo wyłączyłeś go ręcznie).':'.'):'Autopilot działa tu dzięki informacji o AI w Twoim bio.'));
 let b=el('button',off?'primary':'secondary',off?'Włącz z powrotem':'Wyłącz w tej rozmowie');b.onclick=async()=>{if(off)await api('/api/threads/'+encodeURIComponent(t.id)+'/grant','PUT',{enabled:true,participant_consent:true,disclosed:true});else await api('/api/threads/'+encodeURIComponent(t.id)+'/grant','PUT',{enabled:false,participant_consent:false,disclosed:false});await refresh();document.getElementById('panel').close()};p.append(b);return}
old=old||{};p.append(el('p','','Autopilot wysyła odpowiedzi bez Twojego kliknięcia. Najprościej włączyć go dla wszystkich rozmów naraz: dodaj informację o AI do bio (Ustawienia → Tinder). Możesz też włączyć go tylko tu, jeśli ta osoba wie, że pomaga Ci AI.'));
let fields={};for(let [k,lab] of [['disclosed','Ta osoba wie, że odpowiedzi pisze lub pomaga pisać AI'],['participant_consent','Nie ma nic przeciwko'],['enabled','Włącz autopilota w tej rozmowie']]){let[w,i]=field(lab,old[k],'checkbox');fields[k]=i;p.append(w)}
if(t.platform==='tinder'&&!conn.auto_send)p.append(el('div','callout warn','Automatyczne wysyłanie jest wyłączone dla całego konta (Ustawienia → Tinder).'));
let save=el('button','primary','Zapisz');save.onclick=async()=>{await api('/api/threads/'+encodeURIComponent(t.id)+'/grant','PUT',Object.fromEntries(Object.entries(fields).map(([k,v])=>[k,v.checked])));await refresh();document.getElementById('panel').close()};p.append(save)}
function pendingQueue(){if(!data)return[];return data.threads.filter(t=>t.state==='needs_reply'||t.state==='new_match').map(t=>[t,data.drafts.find(d=>d.thread_id===t.id&&d.status==='pending'&&d.anchor_message_id===(t.latest_message_id||OPENER)&&!['demo_placeholder','model_error'].includes(d.generator))]).filter(x=>x[1]).sort((a,b)=>tsOf(b[0])-tsOf(a[0]))}
function showQueue(skip=new Set()){let q=pendingQueue().filter(([t])=>!skip.has(t.id));let p=panel(q.length?'Odpisz po kolei · zostało '+q.length:'Wszystko odpisane');if(!q.length){p.append(el('p','','Nie ma więcej szkiców do wysłania. Nowe pojawią się, gdy ktoś odpisze.'));return}
let [t,d]=q[0];let who=el('div','qwho');who.append(avatarFor(t,'queue'),el('b','',t.display_name+(t.profile?.age?', '+t.profile.age:'')));p.append(who);
let hist=el('div','qhist');for(let m of (data.messages[t.id]||[]).slice(-4))hist.append(el('div','bubble'+(m.sender==='you'?' you':''),m.body));if(!hist.children.length)hist.append(el('div','muted',t.profile?.bio?'Jej opis: '+t.profile.bio:'Pierwsza wiadomość. Ta osoba nie ma opisu.'));p.append(hist);
let ta=el('textarea','draftedit');ta.value=d.body;ta.rows=3;ta.maxLength=1000;p.append(ta);let err=el('p','cerr');err.hidden=true;
let row=el('div','controls');let yes=el('button','primary','Wyślij i dalej');let next=el('button','secondary','Pomiń');let again=el('button','secondary','Napisz inaczej');
yes.onclick=async()=>{let body=ta.value.trim();if(!body)return;yes.disabled=true;try{await api('/api/drafts/'+d.id+'/approve','POST',body!==d.body?{body}:undefined);await refresh();showQueue(skip)}catch(e){err.hidden=false;err.textContent=ERR_PL[e.message]||e.message;yes.disabled=false}};
next.onclick=()=>{skip.add(t.id);showQueue(skip)};again.onclick=async()=>{again.disabled=true;try{await api('/api/threads/'+encodeURIComponent(t.id)+'/regenerate','POST');await refresh();skip.add(t.id);showQueue(skip)}catch(e){err.hidden=false;err.textContent=e.message;again.disabled=false}};
ta.onkeydown=e=>{if(e.key==='Enter'&&(e.metaKey||e.ctrlKey)){e.preventDefault();yes.click()}};row.append(yes,next,again);p.append(row,err);ta.focus()}
async function pauseAll(){await api('/api/settings','PUT',{...data.settings,paused:!data.settings.paused});await refresh()}
function connBanner(on,text){let b=document.getElementById('conn-banner');if(!b){b=el('div','connbanner');b.id='conn-banner';b.setAttribute('role','status');document.body.prepend(b)}b.hidden=!on;if(text)b.textContent=text}
let failures=0;
let fastTimer=null,fastSince=0;
function writing(){let t=data&&data.threads.find(x=>x.id===selected);if(t&&t.state==='new_match'&&data.campaign?.items?.[t.id]?.status==='queued'&&!data.drafts.some(d=>d.thread_id===t.id&&d.anchor_message_id===OPENER&&d.status==='pending'))return true;return !!t&&data.llm_enabled&&t.state==='needs_reply'&&!data.drafts.some(d=>d.thread_id===t.id&&d.anchor_message_id===t.latest_message_id&&['pending','needs_user','no_reply'].includes(d.status))}
function fastPoll(){if(!writing()){fastSince=0;return}if(!fastSince)fastSince=Date.now();if(Date.now()-fastSince>90000||fastTimer)return;fastTimer=setTimeout(()=>{fastTimer=null;if(!document.getElementById('panel').open)safeRefresh()},1500)}
/* One refresh at a time: on a slow server (a big inbox on a small machine) a new request every 5 s piled up behind the previous one
   and made it slower still. */
let REFRESHING=false;
async function safeRefresh(){if(REFRESHING)return;REFRESHING=true;try{await safeRefreshOnce()}finally{REFRESHING=false}}
async function safeRefreshOnce(){try{await refresh();if(failures)connBanner(false);failures=0;fastPoll()}catch(e){failures++;
 if(e.status===401){location.reload();return}
 connBanner(true,data?'Brak połączenia z serwerem. Pokazuję ostatnie dane, ponawiam…':'Łączę z serwerem… Jeśli właśnie był restart, to potrwa kilkanaście sekund.')}}
setInterval(()=>{if(view==='stats'&&!document.hidden&&!document.getElementById('panel').open)renderStats()},60000)  // relative times and the 6-hour rule move on without new data
safeRefresh();setInterval(()=>{if(!document.hidden&&!document.getElementById('panel').open&&!document.getElementById('viewer')?.open)safeRefresh()},5000)
document.addEventListener('visibilitychange',()=>{if(!document.hidden&&!document.getElementById('panel').open)safeRefresh()})


document.getElementById('tab-settings').addEventListener('click',()=>showSettings());document.getElementById('queue-btn')?.addEventListener('click',()=>showQueue());document.getElementById('logout').addEventListener('click',logoutNow);document.getElementById('autopilot-btn').addEventListener('click',showAutopilot);document.getElementById('pause-all').addEventListener('click',pauseAll);document.getElementById('close-panel').addEventListener('click',()=>document.getElementById('panel').close());

let view='chats';
function setView(v){view=v;for(let [id,name] of [['tab-chats','chats'],['tab-auto','auto'],['tab-stats','stats'],['tab-settings','settings']])document.getElementById(id).classList.toggle('active',v===name);document.querySelector('main').hidden=v!=='chats';document.getElementById('roster-wrap').hidden=v!=='chats';renderOnboarding();document.getElementById('auto-view').hidden=v!=='auto';if(v==='auto')renderAuto();document.getElementById('stats-view').hidden=v!=='stats';document.getElementById('settings-view').hidden=v!=='settings';if(v==='stats'){S.anim=true;renderStats()}}
async function logoutNow(){try{await api('/auth/logout','POST')}catch(e){}location.href=data&&data.account_url?data.account_url+'/zaloguj':'/'}
function renderRoster(){let box=document.getElementById('roster');box.replaceChildren();if(!data)return;
let todo=data.threads.filter(t=>t.state==='new_match').sort((a,b)=>matchedOf(b)-matchedOf(a)),reply=data.threads.filter(t=>t.state==='needs_reply').sort((a,b)=>tsOf(b)-tsOf(a));
document.getElementById('roster-title').textContent='Do napisania · '+todo.length+' nowych'+(reply.length?' · '+reply.length+' czeka na Twoją odpowiedź':'');
let cb=document.getElementById('campaign-btn');if(cb){let run=!!data.campaign?.running;cb.hidden=false;cb.textContent=run?'Automatyzuj · trwa':todo.length?'Automatyzuj ('+todo.length+')':'Automatyzuj';cb.onclick=showCampaign}
let qn=pendingQueue().length,qb=document.getElementById('queue-btn');if(qb){qb.hidden=!qn;qb.textContent='Odpisz po kolei ('+qn+')'}
if(!todo.length&&!reply.length){box.append(el('div','roster-empty','Wszystko odpisane. Nowe dopasowania pojawią się tutaj.'));return}
for(let t of [...todo,...reply]){let b=el('button','rost'+(selected===t.id?' sel':''));let u=safeImg(t.profile?.photos?.[0]);
if(u){b.append(cachedImg('roster:'+t.id,u,'rimg',t.display_name))}else b.append(el('div','rinit',(t.display_name||'?').slice(0,1).toUpperCase()));
let ci=data.campaign?.items?.[t.id]?.status;b.append(el('span','rtag'+(t.state==='needs_reply'||ci==='queued'||ci==='review'?' wait':''),t.state==='needs_reply'?'ODPISZ':ci==='queued'?'W KOLEJCE':ci==='review'?'SZKIC':'NOWY'),el('div','rover',t.display_name+(t.profile?.age?', '+t.profile.age:'')));
b.onclick=()=>{setView('chats');choose(t.id)};box.append(b)}}
function tile(big,cap){let t=el('div','tile');t.append(el('div','big',big),el('div','cap',cap));return t}
function kv(k,v){let r=el('div','kv');r.append(el('span','',k),el('b','',v));return r}
/* ---------- Statystyki: liczone w przeglądarce z danych synchronizacji (wiadomości, profile, plan rozmowy) ---------- */
const SD=864e5,SH=36e5,SM=6e4,SNS='http://www.w3.org/2000/svg',DAYS_PL=['Pn','Wt','Śr','Cz','Pt','Sb','Nd'],DAYS_LONG=['poniedziałki','wtorki','środy','czwartki','piątki','soboty','niedziele'];
const S={range:30,anim:true};
const REDUCED=window.matchMedia&&matchMedia('(prefers-reduced-motion: reduce)').matches;
function sv(tag,attrs,parent,text){let n=document.createElementNS(SNS,tag);for(let k in attrs||{})n.setAttribute(k,attrs[k]);if(text!==undefined)n.textContent=text;if(parent)parent.append(n);return n}
function med(a){if(!a.length)return null;let s=[...a].sort((x,y)=>x-y),m=s.length>>1;return s.length%2?s[m]:(s[m-1]+s[m])/2}
function pl(n,a,b,c){let m=n%100,d=n%10;return n===1?a:(d>=2&&d<=4&&!(m>=12&&m<=14))?b:c}
function n1(x){return String(Math.round(x*10)/10).replace('.',',')}
function dur(ms){if(ms==null)return '—';let m=ms/SM;if(m<1)return '<1 min';if(m<60)return Math.round(m)+' min';let h=m/60;if(h<24)return n1(h)+' godz.';return n1(h/24)+' dn.'}
function names(list,max=3){let n=list.slice(0,max).map(t=>t.display_name);return n.join(', ')+(list.length>max?' i '+(list.length-max)+' '+pl(list.length-max,'inna','inne','innych'):'')}
function rangeLabel(r){return r===7?'ostatnie 7 dni':r===30?'ostatnie 30 dni':'cały okres'}

/* Jedna rozmowa = lista wiadomości + "serie" (kolejne wiadomości tej samej osoby). Odpowiedź = następna seria jest od drugiej strony. */
function statsThreads(){return data.threads.map(t=>{let h=(data.messages[t.id]||[]).map(m=>({sender:m.sender==='you'?'you':'them',body:m.body||'',ts:Date.parse(m.created_at)||0})).filter(m=>m.ts).sort((a,b)=>a.ts-b.ts);
 let runs=[];for(let m of h){let r=runs[runs.length-1];if(r&&r.sender===m.sender){r.last=m;r.n++}else runs.push({sender:m.sender,first:m,last:m,n:1})}
 return {t,h,runs,matched:Date.parse(t.matched_at)||h[0]?.ts||0}})}
/* Czy nasza seria "dostała szansę" na odpowiedź: odpowiedź jest, albo minęło >6 h (świeże ciszy nie liczymy jako braku odpowiedzi). */
function askedRun(x,i,now){let run=x.runs[i];if(run.sender!=='you')return null;let nx=x.runs[i+1];if(nx)return {answered:true,delay:nx.first.ts-run.last.ts};return now-run.last.ts>6*SH?{answered:false}:null}
function winMetrics(th,lo,hi,now){let r={matches:0,theirs:0,yours:0,asked:0,answered:0,theirDelays:[],yourDelays:[]};
 for(let x of th){if(x.matched>=lo&&x.matched<hi)r.matches++;
  for(let m of x.h)if(m.ts>=lo&&m.ts<hi)m.sender==='you'?r.yours++:r.theirs++;
  x.runs.forEach((run,i)=>{let a=askedRun(x,i,now);if(a&&run.last.ts>=lo&&run.last.ts<hi){r.asked++;if(a.answered){r.answered++;r.theirDelays.push(a.delay)}}
   let nx=x.runs[i+1];if(run.sender==='them'&&nx&&nx.first.ts>=lo&&nx.first.ts<hi)r.yourDelays.push(nx.first.ts-run.last.ts)})}
 r.rate=r.asked>=5?Math.round(100*r.answered/r.asked):null;r.theirMed=med(r.theirDelays);r.yourMed=med(r.yourDelays);return r}
function dailySeries(th,days,now,pick){let a=new Array(days).fill(0);for(let x of th)for(let ts of pick(x)){let i=Math.floor((now-ts)/SD);if(i>=0&&i<days)a[days-1-i]++}return a}
function rate(a,b){return b?Math.round(100*a/b):null}
function bucketStats(samples,defs){return defs.map(d=>{let s=samples.filter(d.test);let ans=s.filter(x=>x.answered).length;return {label:d.label,n:s.length,rate:s.length>=5?rate(ans,s.length):null}})}

function computeStats(range){let now=Date.now(),th=statsThreads(),span=range*SD,from=range?now-span:0;
 let cur=winMetrics(th,from,now+1,now),prev=range?winMetrics(th,from-span,from,now):null;
 let sd=Math.min(range||30,30);
 let spark={matches:dailySeries(th,sd,now,x=>[x.matched]),theirs:dailySeries(th,sd,now,x=>x.h.filter(m=>m.sender==='them').map(m=>m.ts)),rate:[]};
 for(let d=0;d<sd;d++){let end=now-(sd-1-d)*SD;spark.rate.push(winMetrics(th,end-7*SD,end+1,now).rate)}
 let heat=Array.from({length:7},()=>new Array(24).fill(0)),heatN=0;
 for(let x of th)for(let m of x.h)if(m.sender==='them'&&m.ts>=from){let d=new Date(m.ts);heat[(d.getDay()+6)%7][d.getHours()]++;heatN++}
 let parts=[['rano',6,12],['po południu',12,18],['wieczorem',18,24],['w nocy',0,6]].map(([label,a,b])=>({label,a,b,n:heat.reduce((s,row)=>s+row.slice(a,b).reduce((p,v)=>p+v,0),0)}));
 let dayTot=heat.map(r=>r.reduce((p,v)=>p+v,0));
 // Cechy naszych wiadomości vs to, czy dostały odpowiedź.
 let samples=[],opened=0,openedAns=0,ageB={};
 for(let x of th){x.runs.forEach((run,i)=>{let a=askedRun(x,i,now);if(a&&run.last.ts>=from)samples.push({len:run.last.body.length,q:/\?\s*$/.test(run.last.body.trim()),answered:a.answered})});
  if(x.h[0]?.sender==='you'&&x.h[0].ts>=from){let ans=x.h.some(m=>m.sender==='them');if(ans||now-x.h[0].ts>6*SH){opened++;if(ans)openedAns++}}
  let age=x.t.profile?.age;if(age&&x.matched>=from){let asked=x.runs.some((_,i)=>askedRun(x,i,now));if(asked){let g=age<25?'18–24':age<30?'25–29':age<35?'30–34':'35+';ageB[g]=ageB[g]||{n:0,a:0};ageB[g].n++;if(x.runs.some((r,i)=>r.sender==='you'&&x.runs[i+1]))ageB[g].a++}}}
 let byLen=bucketStats(samples,[{label:'do 30 znaków',test:s=>s.len<30},{label:'30–70 znaków',test:s=>s.len>=30&&s.len<70},{label:'70+ znaków',test:s=>s.len>=70}]);
 let byQ=bucketStats(samples,[{label:'z pytaniem na końcu',test:s=>s.q},{label:'bez pytania',test:s=>!s.q}]);
 let byAge=['18–24','25–29','30–34','35+'].map(g=>({label:g+' lat',n:ageB[g]?.n||0,rate:(ageB[g]?.n||0)>=3?rate(ageB[g].a,ageB[g].n):null}));
 let depth=[['Bez rozmowy',0,0],['1 wymiana',1,1],['2–3',2,3],['4–6',4,6],['7+',7,1e9]].map(([label,a,b])=>({label,n:data.threads.filter(t=>t.state!=='archived'&&(a===0?!t.message_count:t.message_count&&(t.plan?.exchanges||0)>=a&&(t.plan?.exchanges||0)<=b)).length}));
 let ghosted=th.filter(x=>x.h.length&&x.h[x.h.length-1].sender==='you'&&now-x.h[x.h.length-1].ts>3*SD&&x.t.state!=='archived'&&x.t.plan?.stage!=='date_set').map(x=>x.t);
 let buckets=[['< 5 min',0,5*SM],['5–30 min',5*SM,30*SM],['30 min – 2 h',30*SM,2*SH],['2–12 h',2*SH,12*SH],['12 h +',12*SH,1e18]].map(([label,a,b])=>({label,n:cur.theirDelays.filter(d=>d>=a&&d<b).length}));
 return {now,range,th,cur,prev,spark,heat,heatN,parts,dayTot,byLen,byQ,byAge,depth,ghosted,buckets,opened,openedAns,samples:samples.length}}

/* ---------- małe klocki UI ---------- */
function statsTip(){let t=document.getElementById('stip');if(!t){t=el('div','');t.id='stip';t.setAttribute('role','tooltip');t.hidden=true;document.body.append(t)}return t}
function hover(node,lines){let t=statsTip();const show=e=>{t.replaceChildren(el('b','',lines[0]));for(let l of lines.slice(1))t.append(el('div','',l));t.hidden=false;let r=node.getBoundingClientRect();let x=e.clientX!==undefined&&e.type!=='focus'?e.clientX:r.left+r.width/2,y=e.clientX!==undefined&&e.type!=='focus'?e.clientY:r.top;let w=t.offsetWidth,h=t.offsetHeight;t.style.left=Math.max(8,Math.min(innerWidth-w-8,x-w/2))+'px';t.style.top=(y-h-12<8?y+18:y-h-12)+'px'};
 node.addEventListener('mouseenter',show);node.addEventListener('mousemove',show);node.addEventListener('focus',show);for(let ev of ['mouseleave','blur'])node.addEventListener(ev,()=>{t.hidden=true})}
function countUp(node,val,fmt){fmt=fmt||(v=>String(Math.round(v)));if(!S.anim||REDUCED||typeof val!=='number'){node.textContent=typeof val==='number'?fmt(val):val;return}let t0=performance.now();const step=t=>{let k=Math.min(1,(t-t0)/800);node.textContent=fmt(val*(1-Math.pow(1-k,3)));if(k<1)requestAnimationFrame(step)};requestAnimationFrame(step)}
function spark(vals,w=104,h=30){let s=sv('svg',{viewBox:`0 0 ${w} ${h}`,width:w,height:h,class:'spark','aria-hidden':'true'});let pts=vals.map((v,i)=>v==null?null:[i,v]).filter(Boolean);if(pts.length<2)return s;
 let mx=Math.max(...pts.map(p=>p[1]),1),X=i=>2+i*(w-4)/Math.max(1,vals.length-1),Y=v=>h-4-v/mx*(h-9);let d=pts.map((p,i)=>(i?'L':'M')+X(p[0]).toFixed(1)+' '+Y(p[1]).toFixed(1)).join(' ');
 sv('path',{d:d+` L${X(pts[pts.length-1][0])} ${h-2} L${X(pts[0][0])} ${h-2} Z`,class:'sp-area'},s);sv('path',{d,class:'sp-line'},s);let l=pts[pts.length-1];sv('circle',{cx:X(l[0]),cy:Y(l[1]),r:3,class:'sp-dot'},s);return s}
function deltaPill(cur,prev,unit='',lowerBetter=false){if(prev==null||cur==null)return null;let d=cur-prev;let flat=Math.abs(d)<(unit==='%'?1:0.5);let good=lowerBetter?d<0:d>0;let p=el('span','delta '+(flat?'flat':good?'up':'down'));p.append(el('i','',flat?'→':d>0?'▲':'▼'),document.createTextNode(flat?'bez zmian':(d>0?'+':'−')+Math.abs(Math.round(d))+(unit==='%'?' pp':unit)));return p}
function timeDelta(cur,prev){let d=cur-prev;if(Math.abs(d)<5*SM)return deltaPill(0,0);let p=el('span','delta '+(d<0?'up':'down'));p.append(el('i','',d<0?'▼':'▲'),document.createTextNode((d<0?'−':'+')+dur(Math.abs(d))));return p}
function kpi(label,value,fmt,dp,sp,note){let c=el('div','kpi');c.append(el('div','kl',label));let big=el('div','kbig');c.append(big);countUp(big,value,fmt);let foot=el('div','kfoot');if(dp)foot.append(dp);else if(note)foot.append(el('span','knote',note));if(sp)foot.append(sp);c.append(foot);return c}
function secCard(title,sub,cls){let c=el('section','cardx scard'+(cls?' '+cls:''));let h=el('div','shead');h.append(el('h2','',title));if(sub)h.append(el('p','ssub',sub));c.append(h);return c}
function barRow(label,val,max,txt,muted){let r=el('div','brow'+(muted?' dim':''));let b=el('div','btrack'),f=el('div','bfill');f.style.width=(muted||!max?0:Math.max(3,100*val/max))+'%';b.append(f);r.append(el('span','blab',label),b,el('b','bval',txt));return r}

/* ---------- sekcje ---------- */
function heroBlock(m,st,sent){let c=el('section','hero');let L=el('div','hleft'),R=el('div','hright');
 let r=m.cur.rate,ring=sv('svg',{viewBox:'0 0 180 180',class:'hring',role:'img','aria-label':r==null?'Za mało danych':'Wskaźnik odpowiedzi '+r+'%'});
 let defs=sv('defs',{},ring),g=sv('linearGradient',{id:'hg',x1:'0',y1:'0',x2:'1',y2:'1'},defs);sv('stop',{offset:'0',class:'g0'},g);sv('stop',{offset:'1',class:'g1'},g);
 const C=2*Math.PI*74;sv('circle',{cx:90,cy:90,r:74,class:'rtrack'},ring);
 if(r!=null&&r>0){let arc=sv('circle',{cx:90,cy:90,r:74,class:'rarc',transform:'rotate(-90 90 90)','stroke-dasharray':C.toFixed(1),'stroke-dashoffset':(C*(1-r/100)).toFixed(1)},ring);arc.style.setProperty('--c0',C.toFixed(1));arc.style.setProperty('--c1',(C*(1-r/100)).toFixed(1))}
 let rw=el('div','hringwrap');rw.append(ring);let mid=el('div','hmid');let big=el('b','',''),cap=el('small','','odpowiedzi');mid.append(big,cap);rw.append(mid);countUp(big,r==null?'—':r,v=>Math.round(v)+'%');L.append(rw);
 let tx=el('div','htext');tx.append(el('div','heyebrow','Twoja skuteczność · '+rangeLabel(m.range)));
 let verdict=r==null?'Za mało danych':r>=60?'Rozmowy wyraźnie się kleją':r>=40?'Solidnie, z miejscem na więcej':r>=20?'Jest co poprawić':'Odpowiedzi są rzadkie';
 tx.append(el('h2','hverdict',verdict));
 tx.append(el('p','hsub',r==null?'Potrzeba co najmniej 5 Twoich wiadomości z czasem na odpowiedź. Zmień zakres na „Cały okres” albo wróć po kolejnej synchronizacji.':'Na '+m.cur.answered+' z '+m.cur.asked+' '+pl(m.cur.asked,'Twojej wiadomości','Twoich wiadomości','Twoich wiadomości')+' przyszła odpowiedź ('+rangeLabel(m.range)+'). Liczymy tylko wiadomości starsze niż 6 godzin, żeby nie karać świeżych.'));
 if(sent>0){let h=sent/60;let pill=el('div','hsaved');pill.append(el('b','','≈ '+(h<1?Math.round(sent)+' min':n1(h)+' godz.')),document.createTextNode(' pisania zaoszczędzone przez Winq · '+sent+' '+pl(sent,'wiadomość wysłana','wiadomości wysłane','wiadomości wysłanych')+' (szacunek: 1 min na wiadomość)'));tx.append(pill)}
 L.append(tx);
 let f=st.funnel||{},steps=[['Dopasowania',f.matches||0],['Rozmowy',f.conversations||0],...(statsAdv()?[['Spotkania',f.confirmed||0]]:[])];
 for(let [i,[lab,v]] of steps.entries()){let s=el('div','hstep');let b=el('b','',''),sm=el('small','',lab);s.append(b,sm);countUp(b,v);if(i)s.append(el('span','hconv',steps[i-1][1]?'↳ '+rate(v,steps[i-1][1])+'%':''));R.append(s)}
 c.append(L,R);return c}

function kpiRow(m){let row=el('div','kpis'),c=m.cur,p=m.prev,sp=m.range||30;
 row.append(kpi('Nowe dopasowania',c.matches,null,deltaPill(c.matches,p?.matches),spark(m.spark.matches)),
  kpi('Wiadomości od nich',c.theirs,null,deltaPill(c.theirs,p?.theirs),spark(m.spark.theirs)),
  kpi('Wskaźnik odpowiedzi',c.rate==null?'—':c.rate,v=>Math.round(v)+'%',deltaPill(c.rate,p?.rate,'%'),spark(m.spark.rate),c.rate==null?'za mało danych':''),
  kpi('Typowy czas odpowiedzi',c.theirMed==null?'—':c.theirMed,v=>dur(v),p&&c.theirMed!=null&&p.theirMed!=null?timeDelta(c.theirMed,p.theirMed):null,null,c.theirMed==null?'za mało danych':'mediana ich odpowiedzi'));
 return row}

function insightsBlock(m,st,sent){let list=[],th=data.threads,c=m.cur;
 let needs=th.filter(t=>t.state==='needs_reply');
 if(needs.length)list.push({p:1,i:'💬',tone:'hot',h:needs.length+' '+pl(needs.length,'osoba czeka','osoby czekają','osób czeka')+' na odpowiedź',t:names(needs)+'. Im szybciej odpiszesz, tym większa szansa na ciąg dalszy.'});
 let inv=th.filter(t=>t.plan?.stage==='invite');if(inv.length)list.push({p:2,i:'🔥',tone:'hot',h:inv.length+' '+pl(inv.length,'rozmowa jest','rozmowy są','rozmów jest')+' w oknie na zaproszenie',t:names(inv)+': sygnały zainteresowania są dobre, warto zaproponować spotkanie.'});
 if(m.heatN>=8){let best=[...m.parts].sort((a,b)=>b.n-a.n)[0],share=Math.round(100*best.n/m.heatN),bd=m.dayTot.indexOf(Math.max(...m.dayTot));list.push({p:3,i:'🕘',h:share+'% wiadomości od nich przychodzi '+best.label+' ('+best.a+'–'+best.b+')',t:'Najaktywniejsze są '+DAYS_LONG[bd]+'. Wtedy najłatwiej złapać rozmowę „na żywo”.'})}
 let q=m.byQ;if(q[0].rate!=null&&q[1].rate!=null&&Math.abs(q[0].rate-q[1].rate)>=10){let w=q[0].rate>q[1].rate;list.push({p:4,i:'❓',h:(w?'Pytanie na końcu':'Wiadomość bez pytania')+' dostaje odpowiedź częściej',t:'Z pytaniem: '+q[0].rate+'% (n='+q[0].n+'), bez: '+q[1].rate+'% (n='+q[1].n+').'})}
 let ls=m.byLen.filter(x=>x.rate!=null);if(ls.length>=2){let b=[...ls].sort((a,b)=>b.rate-a.rate),w=b[b.length-1];if(b[0].rate-w.rate>=12)list.push({p:5,i:'✍️',h:'Najlepiej działają wiadomości: '+b[0].label,t:b[0].rate+'% odpowiedzi wobec '+w.rate+'% dla „'+w.label+'”.'})}
 if(c.theirMed!=null&&c.theirDelays.length>=3)list.push({p:6,i:'⏱️',h:'Odpowiadają zwykle w ciągu '+dur(c.theirMed),t:c.yourMed!=null?'Ty (z agentem) reagujesz po ok. '+dur(c.yourMed)+'.':'Tak wygląda mediana z ostatnich wymian.'});
 if(m.ghosted.length)list.push({p:7,i:'👻',tone:'cold',h:m.ghosted.length+' '+pl(m.ghosted.length,'rozmowa ucichła','rozmowy ucichły','rozmów ucichło')+' po Twojej wiadomości (3 dni +)',t:names(m.ghosted)+'. Możesz je odpuścić albo zagadać o czymś nowym.'});
 let ag=m.byAge.filter(x=>x.rate!=null);if(ag.length>=2){let b=[...ag].sort((a,b)=>b.rate-a.rate);if(b[0].rate-b[b.length-1].rate>=20)list.push({p:8,i:'🎯',h:'Najlepsza odpowiedzialność: '+b[0].label,t:b[0].rate+'% rozmów z odpowiedzią (n='+b[0].n+'), najsłabiej '+b[b.length-1].label+': '+b[b.length-1].rate+'%.'})}
 list.sort((a,b)=>a.p-b.p);list=list.slice(0,6);
 let card=secCard('Co zauważył Winq','Wnioski z Twoich rozmów. Pojawiają się dopiero, gdy jest dość danych, żeby nie zgadywać.','insights');
 if(!list.length){card.append(el('p','sempty','Za mało danych na wnioski. Pierwsze pojawią się po ok. 20 wymienionych wiadomościach.'));return card}
 let g=el('div','igrid');for(let x of list){let it=el('div','insight'+(x.tone?' '+x.tone:''));it.append(el('span','iico',x.i),el('div','','')); it.lastChild.append(el('b','',x.h),el('p','',x.t));g.append(it)}card.append(g);return card}

function hotBlock(){let hot=data.threads.filter(t=>t.plan&&t.state!=='archived'&&t.state!=='paused'&&(['invite','logistics','date_set'].includes(t.plan.stage)||t.plan.interest>=70)).sort((a,b)=>b.plan.interest-a.plan.interest).slice(0,5);
 let card=secCard('Gorące teraz','Rozmowy, w których dzieje się najwięcej. Kliknij, żeby przejść do czatu.','hot');
 if(!hot.length){card.append(el('p','sempty','Nic się jeszcze nie rozgrzało. Gdy ktoś zacznie odpisywać z zaangażowaniem, pojawi się tutaj.'));return card}
 for(let t of hot){let b=el('button','hrow');b.type='button';let av=avatarFor(t,'stats');b.append(av);let w=el('div','hinfo');w.append(el('b','',t.display_name+(t.profile?.age?', '+t.profile.age:'')),el('small','',t.plan.stage_label+' · '+t.plan.move_label));b.append(w);
  let sc=el('div','hscore');sc.append(el('b','',t.plan.interest),el('small','','/100'));let bar=el('div','hbar'),f=el('i','');f.style.width=t.plan.interest+'%';bar.append(f);sc.append(bar);b.append(sc);b.onclick=()=>{setView('chats');choose(t.id)};card.append(b)}
 return card}

function funnelBlock(st){let f=st.funnel||{};let steps=[['matches','Dopasowania','każde dopasowanie'],['conversations','Rozmowy','ktoś napisał'],['invited','Zaproszenie padło','propozycja spotkania'],['agreed','Zgoda','termin się klei'],['confirmed','Spotkanie','dzień, godzina i miejsce']];
 let card=secCard('Droga do spotkania','Cały lejek od dopasowania do potwierdzonej randki. Procent pod spodem to przejście z poprzedniego kroku.','funnel');
 let max=Math.max(1,f.matches||0),worst=null;steps.forEach(([k],i)=>{if(i<1)return;let a=f[steps[i-1][0]]||0,b=f[k]||0;if(a>=3){let r=b/a;if(worst==null||r<worst.r)worst={i,r}}});
 let wrap=el('div','fun');steps.forEach(([k,lab,hint],i)=>{let v=f[k]||0,prevV=i?f[steps[i-1][0]]||0:null;let row=el('div','fstep'+(worst&&worst.i===i?' leak':'')+(v?'':' zero'));
  let bar=el('div','fbar2');let fill=el('div','ffill');fill.style.width=Math.max(v?6:0,100*v/max)+'%';fill.style.setProperty('--o',String(1-i*0.11));bar.append(fill);
  let left=el('div','fname');left.append(el('b','',lab),el('small','',hint));let right=el('div','fnum');right.append(el('b','',v));if(i)right.append(el('small','',prevV?Math.min(100,Math.round(100*v/prevV))+'%':'—'));
  row.append(left,bar,right);if(worst&&worst.i===i)row.append(el('span','fleak','Tu uciekają najczęściej'));wrap.append(row)});
 card.append(wrap);return card}

function constellation(m){let card=secCard('Mapa zainteresowania','Każda bańka to rozmowa. Wyżej = większe zainteresowanie, bardziej na prawo = starsze dopasowanie, większa = więcej wiadomości.','const');
 let items=data.threads.filter(t=>t.plan&&t.state!=='archived');if(!items.length){card.append(el('p','sempty','Brak rozmów do pokazania.'));return card}
 let W=720,H=340,L=46,R=18,T=16,B=36,pw=W-L-R,ph=H-T-B,now=m.now;
 let ages=items.map(t=>Math.max(0,(now-(Date.parse(t.matched_at)||Date.parse(t.sort_at)||now))/SD));let X=Math.max(7,Math.ceil(Math.max(...ages)));
 let svg=sv('svg',{viewBox:`0 0 ${W} ${H}`,class:'cmap',role:'img','aria-label':'Mapa zainteresowania: '+items.length+' rozmów'});
 let defs=sv('defs',{},svg),g=sv('linearGradient',{id:'cg',x1:'0',y1:'0',x2:'1',y2:'1'},defs);sv('stop',{offset:'0',class:'g0'},g);sv('stop',{offset:'1',class:'g1'},g);
 const px=d=>L+d/X*pw,py=v=>T+ph-v/100*ph;
 sv('rect',{x:L,y:py(100),width:pw,height:py(70)-py(100),class:'czone'},svg);sv('text',{x:W-R-10,y:py(100)+16,class:'czl','text-anchor':'end'},svg,'Strefa zaproszenia');
 for(let v of [0,25,50,75,100]){sv('line',{x1:L,x2:W-R,y1:py(v),y2:py(v),class:'cgrid'},svg);sv('text',{x:L-8,y:py(v)+4,class:'cax','text-anchor':'end'},svg,String(v))}
 sv('text',{x:L,y:H-10,class:'cax'},svg,'świeże dopasowania');sv('text',{x:W-R,y:H-10,class:'cax','text-anchor':'end'},svg,'starsze · '+X+' '+pl(X,'dzień','dni','dni')+' →');
 sv('text',{x:12,y:T+ph/2,class:'cax',transform:`rotate(-90 12 ${T+ph/2})`,'text-anchor':'middle'},svg,'zainteresowanie');
 let pts=items.map((t,i)=>({t,x:px(ages[i]),y:py(t.plan.interest),r:13+Math.min(11,Math.sqrt(t.message_count||0)*2)}));
 for(let it=0;it<80;it++){let moved=false;for(let i=0;i<pts.length;i++)for(let j=i+1;j<pts.length;j++){let a=pts[i],b=pts[j],dx=b.x-a.x,dy=b.y-a.y,d=Math.hypot(dx,dy),min=a.r+b.r+3;if(d<min){if(d<.01){dx=(i%2?1:-1);dy=.5;d=1.1}let k=(min-d)/2/d;a.x-=dx*k;a.y-=dy*k;b.x+=dx*k;b.y+=dy*k;moved=true}}
  for(let p of pts){p.x=Math.max(L+p.r,Math.min(W-R-p.r,p.x));p.y=Math.max(T+p.r,Math.min(T+ph-p.r,p.y))}if(!moved)break}
 let grp=t=>{let p=t.plan;return ['invite','date_set'].includes(p.stage)||['invite','settle_details','ask_instagram'].includes(p.move)||p.stage==='logistics'?'hot':['fading','cooldown','closed'].includes(p.stage)?'cold':p.stage==='opening'?'new':'warm'};
 pts.sort((a,b)=>b.r-a.r);
 pts.forEach((p,i)=>{let t=p.t,k=grp(t),gr=sv('g',{class:'cdot '+k,tabindex:'0',role:'button','aria-label':t.display_name+', zainteresowanie '+t.plan.interest+', '+t.plan.stage_label,transform:`translate(${p.x.toFixed(1)} ${p.y.toFixed(1)})`},svg);gr.style.setProperty('--i',String(i));
  let u=safeImg(t.profile?.photos?.[0]);sv('circle',{r:p.r,class:'cb'},gr);
  if(u){let id='cp'+i;let cp=sv('clipPath',{id},gr);sv('circle',{r:p.r-2},cp);let im=sv('image',{href:u,x:-p.r,y:-p.r,width:p.r*2,height:p.r*2,'clip-path':`url(#${id})`,preserveAspectRatio:'xMidYMid slice'},gr);im.setAttribute('referrerpolicy','no-referrer')}
  else sv('text',{class:'ci','text-anchor':'middle',dy:'.35em'},gr,(t.display_name||'?').slice(0,1).toUpperCase());
  sv('circle',{r:p.r,class:'cr'},gr);
  hover(gr,[t.display_name+(t.profile?.age?', '+t.profile.age:''),t.plan.stage_label+' · '+t.plan.move_label,'Zainteresowanie '+t.plan.interest+'/100',(t.message_count||0)+' '+pl(t.message_count||0,'wiadomość','wiadomości','wiadomości')]);
  gr.addEventListener('click',()=>{setView('chats');choose(t.id)});gr.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();setView('chats');choose(t.id)}})});
 let wrap=el('div','cwrap');wrap.append(svg);card.append(wrap);
 let lg=el('div','legend clegend');for(let [c,l] of [['hot','Gorące: zaproszenie lub ustalanie'],['warm','Budowanie rozmowy'],['new','Nowe, bez wiadomości'],['cold','Wygasa lub po odmowie']]){let s=el('span','');s.append(el('i','sw '+c),document.createTextNode(l));lg.append(s)}card.append(lg);return card}

function heatBlock(m){let card=secCard('Kiedy do Ciebie piszą','Wiadomości od dopasowań wg dnia tygodnia i godziny (Twój czas lokalny) · '+rangeLabel(m.range),'heat');
 if(m.heatN<5){card.append(el('p','sempty','Za mało wiadomości w tym okresie. Zmień zakres albo wróć po kolejnych synchronizacjach.'));return card}
 let mx=Math.max(1,...m.heat.flat()),grid=el('div','heat');grid.setAttribute('role','img');grid.setAttribute('aria-label','Mapa cieplna aktywności: najwięcej wiadomości '+Math.max(...m.dayTot)+' w jednym dniu tygodnia');
 let hh=el('div','hhours');hh.append(el('span',''));for(let h=0;h<24;h++)hh.append(el('span','',h%6===0?String(h):''));grid.append(hh);
 m.heat.forEach((row,d)=>{let r=el('div','hrow2');r.append(el('span','hday',DAYS_PL[d]));row.forEach((v,h)=>{let c=el('span','hcell');if(v){c.style.setProperty('--a',(0.18+0.82*v/mx).toFixed(2));c.classList.add('on')}hover(c,[DAYS_PL[d]+', '+String(h).padStart(2,'0')+':00–'+String((h+1)%24).padStart(2,'0')+':00',v+' '+pl(v,'wiadomość','wiadomości','wiadomości')+' od nich']);r.append(c)});grid.append(r)});
 card.append(grid);let lg=el('div','heatlg');lg.append(el('span','','mniej'),el('i','hramp'),el('span','','więcej'));card.append(lg);return card}

function speedBlock(m){let card=secCard('Tempo odpowiedzi','Po jakim czasie od Twojej wiadomości odpisuje druga strona · '+rangeLabel(m.range),'speed');let tot=m.buckets.reduce((s,b)=>s+b.n,0);
 if(tot<3){card.append(el('p','sempty','Za mało zakończonych wymian, żeby pokazać rozkład.'));return card}
 let mx=Math.max(...m.buckets.map(b=>b.n)),cols=el('div','cols');for(let [i,b] of m.buckets.entries()){let c=el('div','col');let v=el('b','cv',b.n),bar=el('div','cbar'),f=el('i','');f.style.height=Math.max(b.n?4:0,100*b.n/mx)+'%';f.style.setProperty('--o',String(1-i*0.14));bar.append(f);c.append(v,bar,el('span','cl',b.label));hover(c,[b.label,b.n+' '+pl(b.n,'wymiana','wymiany','wymian')+' ('+rate(b.n,tot)+'%)']);cols.append(c)}
 card.append(cols);let foot=el('div','sfoot');foot.append(kv('Typowy czas odpowiedzi dopasowań',dur(m.cur.theirMed)),kv('Twój czas reakcji (z agentem)',dur(m.cur.yourMed)));card.append(foot);return card}

function worksBlock(m){let card=secCard('Co działa','Jak cechy Twoich wiadomości przekładają się na odpowiedź · '+rangeLabel(m.range),'works');
 const group=(title,rows,unit)=>{card.append(el('h3','wt',title));let any=false;for(let r of rows){let low=r.rate==null;if(!low)any=true;card.append(barRow(r.label,r.rate||0,100,low?'za mało danych (n='+r.n+')':r.rate+'% · n='+r.n,low))}};
 group('Długość wiadomości',m.byLen);group('Zakończenie',m.byQ);
 if(m.opened>=5)group('Kto otwiera rozmowę',[{label:'Ty piszesz pierwszy',rate:rate(m.openedAns,m.opened),n:m.opened}]);
 if(m.byAge.some(x=>x.rate!=null))group('Wiek dopasowania (rozmowy z odpowiedzią)',m.byAge);
 card.append(el('p','snote','Odsetek wiadomości (lub rozmów), które dostały odpowiedź. Próbki poniżej 5 nie są pokazywane, żeby nie wyciągać wniosków z przypadku.'));return card}

function depthBlock(m){let card=secCard('Jak głęboko sięgają rozmowy','Liczba pełnych wymian (Ty ↔ ona) w aktywnych rozmowach','depth');let mx=Math.max(1,...m.depth.map(d=>d.n));let cols=el('div','cols');
 for(let [i,d] of m.depth.entries()){let c=el('div','col');let bar=el('div','cbar'),f=el('i','');f.style.height=Math.max(d.n?4:0,100*d.n/mx)+'%';f.style.setProperty('--o',String(0.45+i*0.14));bar.append(f);c.append(el('b','cv',d.n),bar,el('span','cl',d.label));hover(c,[d.label,d.n+' '+pl(d.n,'rozmowa','rozmowy','rozmów')]);cols.append(c)}
 card.append(cols);return card}

/* Ile wiadomości wysłał Winq (do szacunku zaoszczędzonego czasu w kafelku na górze). */
function sentByWinq(st){let n=0;for(let a of st.actions)if(a.status==='sent')n+=a.n;return n}
/* Zweryfikowane rezultaty (randki, Instagram, numery): obiecane w pakiecie Casanova, więc zostają, ale w części zaawansowanej. */
function resultsBlock(st){let card=secCard('Zweryfikowane rezultaty','Tylko to, co da się sprawdzić w rozmowie: potwierdzony termin, podany kontakt.','results');let ks=Object.keys(st.outcomes);
 if(!ks.length){card.append(el('p','sempty','Brak jeszcze rezultatów. Pojawią się, gdy rozmowa zawiera sprawdzalny kontakt lub plan spotkania.'));return card}
 for(let k of ks)card.append(kv(OUTCOME_NAMES[k]||k,st.outcomes[k]));return card}

/* Czy dane są świeże i połączenie działa: bez tego liczby mogłyby być spokojnie nieaktualne. */
function linkStatus(){let cons=data.tinder?.connections||[],now=Date.now(),box=el('div','linkst');let c=cons[0];
 let put=(tone,text,action)=>{box.className='linkst '+tone;box.append(el('i','lsdot'),el('span','',text));if(action){let b=el('button','lsbtn',action[0]);b.type='button';b.onclick=action[1];box.append(b)}return box};
 if(!c)return put('warn','Nie połączono konta Tinder. Połącz je w Ustawieniach, żeby zobaczyć prawdziwe statystyki.',['Ustawienia',()=>{setView('settings');showSettings()}]);
 if(c.error&&!SOFT_ERRORS.has(c.error))return put('bad',tinderErrors[c.error]||('Połączenie z Tinderem wymaga uwagi ('+c.error+').'),['Napraw w Ustawieniach',()=>{setView('settings');showSettings()}]);
 if(c.error&&c.enabled&&c.blocked_until>now/1000)return put('warn',(tinderErrors[c.error]||'Synchronizacja robi przerwę.')+' Wznowi się około '+clockText(c.blocked_until)+'.');
 if(!c.enabled)return put('warn','Połączenie z Tinderem jest wyłączone, dane się nie odświeżają.');
 let ls=Date.parse(c.last_sync||'');if(!ls)return put('warn','Czekamy na pierwszą synchronizację z Tinderem. Pierwszy import może potrwać kilka minut.');
 let min=Math.max(0,Math.round((now-ls)/6e4));let ago=min<1?'przed chwilą':min<60?min+' min temu':min<1440?Math.round(min/60)+' godz. temu':Math.round(min/1440)+' dn. temu';
 if(data.settings?.paused)return put('warn','Winq jest wstrzymany. Ostatnia synchronizacja: '+ago+'.');
 if(min>30)return put('warn','Ostatnia synchronizacja była '+ago+'. Statystyki mogą być nieaktualne.');
 return put('ok','Połączono z Tinderem. Ostatnia synchronizacja: '+ago+'.')}
/* Podstawowe statystyki (kafelki, odpowiedzi, stan połączenia, gorące rozmowy) dostaje każdy pakiet. Zaawansowane (lejek do randki,
   mapa zainteresowania, aktywność dzień po dniu, co działa, zweryfikowane rezultaty) tylko Casanova: data.plan.advanced_stats. */
const statsAdv=()=>!data.plan||data.plan.advanced_stats;
function statsLock(){let c=el('section','cardx statslock');c.append(el('span','lockico','🔒'),el('h2','','Reszta statystyk odblokuje się w pakiecie Casanova'),el('p','','Lejek od dopasowania do umówionej randki, mapa zainteresowania, godziny największej aktywności, to co działa w Twoich wiadomościach i zweryfikowane rezultaty. Pojawią się tu od razu po wykupieniu pakietu.'));let a=upgradeLink('Odblokuj w pakiecie Casanova');a.className='btn';c.append(a);return c}
/* Podgląd tego, co jest za zamkiem: prawdziwe bloki, rozmyte i nieklikalne, z kartą odblokowania na wierzchu. */
function lockedPreview(blocks){let w=el('div','lockwrap'),body=el('div','lockbody');body.setAttribute('aria-hidden','true');body.inert=true;body.append(...blocks);let ov=el('div','lockov');ov.append(statsLock());w.append(body,ov);return w}
function renderStats(){let root=document.getElementById('stats-view');root.replaceChildren();if(!data){root.textContent='Ładowanie...';return}let st=data.stats;if(!st){root.textContent='Brak statystyk.';return}
 root.classList.toggle('anim',S.anim&&!REDUCED);
 let head=el('div','stathead');let ttl=el('div','');ttl.append(el('h2','sttitle','Statystyki'),el('p','stsub','Wszystko, co Winq widzi w Twoich rozmowach, policzone na bieżąco z synchronizacji.'));
 let seg=el('div','seg rangeseg');seg.setAttribute('role','group');seg.setAttribute('aria-label','Zakres czasu');for(let [v,l] of [[7,'7 dni'],[30,'30 dni'],[0,'Cały okres']]){let b=el('button',S.range===v?'active':'',l);b.type='button';b.setAttribute('aria-pressed',S.range===v);b.onclick=()=>{S.range=v;S.anim=false;renderStats()};seg.append(b)}
 head.append(ttl,seg);root.append(head,linkStatus());
 if(!data.threads.length){root.append(el('p','sempty big','Brak danych do analizy. Po pierwszej synchronizacji z Tinderem pojawią się tu Twoje statystyki.'));return}
 let m=computeStats(S.range);
 /* Góra (pasek połączenia, pierścień, cztery kafelki) widzi każdy pakiet. Reszta tylko Casanova, u pozostałych rozmyta za zamkiem. */
 root.append(heroBlock(m,st,sentByWinq(st)),kpiRow(m));
 let deep=[insightsBlock(m,st,0)];
 let two=el('div','sgrid');two.append(constellation(m),hotBlock());deep.push(two);
 let two2=el('div','sgrid even');two2.append(funnelBlock(st),worksBlock(m));deep.push(two2);
 deep.push(heatBlock(m));
 let two3=el('div','sgrid even');two3.append(speedBlock(m),depthBlock(m));deep.push(two3);
 deep.push(resultsBlock(st));
 if(statsAdv())root.append(...deep);else root.append(lockedPreview(deep));
 S.anim=false}
document.getElementById('tab-chats').addEventListener('click',()=>setView('chats'));document.getElementById('tab-auto').addEventListener('click',()=>setView('auto'));document.getElementById('tab-stats').addEventListener('click',()=>setView('stats'));

function renderOnboarding(){const box=document.getElementById('onboard');if(!box||!data)return;updateAutopilotButton();
 let hidden=false;try{hidden=localStorage.getItem('winq-start-hidden')==='1'}catch(e){}
 box.hidden=hidden||apLive(tinderConn())||view!=='chats';if(box.hidden)return;box.replaceChildren();
 const card=el('div','ob');card.append(el('h2','','Uruchom autopilota'),el('p','','4 proste kroki, ok. 3 minuty. Potem Winq sam odpisuje w Twoich rozmowach na Tinderze.'));
 const close=el('button','ob-close','Ukryj');close.onclick=()=>{try{localStorage.setItem('winq-start-hidden','1')}catch(e){}box.hidden=true};card.append(close);
 card.append(startGuide(()=>renderOnboarding()));box.append(card)}

/* ---------- Automatyzuj: agent pisze pierwszą wiadomość do wybranych nowych dopasowań ---------- */
const CAMPAIGN={mode:null,sel:null,msg:null,profile:null,bio:true,win:null};
const CMP_STATUS={queued:'w kolejce',sent:'wysłano',review:'szkic czeka na Ciebie',started:'rozmowa ruszyła',skipped:'pominięto',failed:'nie udało się'};
function fmtDur(sec){let m=Math.round(sec/60);if(m<2)return 'kilka minut';if(m<90)return m+' min';let h=Math.round(m/6)/10;return h+' godz.'}
function autoLive(){return apLive(tinderConn())&&(!data.plan||data.plan.autopilot)}
function autoWhy(){if(data.plan&&!data.plan.autopilot)return 'Pakiet '+data.plan.label+' pisze tylko szkice. Wysyłanie samo jest od pakietu Flirt.';return 'Żeby agent wysyłał sam, włącz autopilota (informacja o AI w Twoim bio). Do tego czasu przygotuje szkice.'}
function openerBox(box,t,send){
 let it=data.campaign?.items?.[t.id],c=data.campaign||{};
 if(it&&it.status==='queued'){let w=el('div','working');w.setAttribute('role','status');w.append(el('span','dots'),el('span','',it.mode==='auto'?'Agent pisze pierwszą wiadomość i wyśle ją za chwilę, w kolejce automatyzacji.':'Agent pisze szkic pierwszej wiadomości. Zwykle kilka sekund.'));box.append(w);return}
 if(!data.llm_enabled){box.append(el('p','','Podłącz model AI w ustawieniach serwera, żeby agent mógł pisać pierwsze wiadomości. Możesz też napisać sam w Tinderze.'));return}
 if(it&&(it.status==='skipped'||it.status==='failed')&&it.note)box.append(el('div','callout warn',it.note));
 box.append(el('p','','Nowe dopasowanie. Napisz pierwszą wiadomość sam w Tinderze albo poproś agenta: nawiąże do jej opisu, a Ty zdecydujesz, czy ją wysłać.'));
 let row=el('div','controls');let ask=el('button','primary','Napisz szkic pierwszej wiadomości');ask.onclick=()=>send('/api/threads/'+encodeURIComponent(t.id)+'/opener',{mode:'draft'},ask);row.append(ask);
 if(autoLive()){let go=el('button','secondary','Napisz i wyślij sam');go.onclick=()=>send('/api/threads/'+encodeURIComponent(t.id)+'/opener',{mode:'auto'},go);row.append(go)}
 box.append(row);
 if(c.free_slots===0)box.append(el('div','callout warn','Wszystkie miejsca w pakiecie '+data.plan.label+' są zajęte. Pierwsza wiadomość zajmie jedno z nich.'))}
const CMP_TITLE='Automatyzuj: pierwsze wiadomości';let CMP_TIMER=null;
function showCampaign(){CAMPAIGN.msg=null;CAMPAIGN.sel=null;CAMPAIGN.win=null;let p=panel(CMP_TITLE);fillCampaign(p);campaignWatch(p)}
/* The page behind a panel does not refresh itself, so while this panel is open it follows the campaign: new numbers show up without a click. */
function campaignWatch(p){clearInterval(CMP_TIMER);let last=JSON.stringify(data.campaign);
 CMP_TIMER=setInterval(async()=>{if(!document.getElementById('panel').open||document.getElementById('panel-title').textContent!==CMP_TITLE){clearInterval(CMP_TIMER);return}
  try{await refresh()}catch(e){return}
  let now=JSON.stringify(data.campaign);if(now===last)return;last=now;
  if(document.activeElement&&p.contains(document.activeElement)&&document.activeElement.matches('input'))return;  // do not pull the list from under a click
  fillCampaign(p)},3000)}
function fillCampaign(p){p.replaceChildren();
 const cs=data.campaign||{items:{},counts:{},profiles:{}},counts=cs.counts||{},live=autoLive(),profiles=cs.profiles||{};
 const waiting=data.threads.filter(t=>t.state==='new_match').sort((a,b)=>matchedOf(b)-matchedOf(a));
 const free=cs.free_slots==null?Infinity:cs.free_slots;
 const eligible=waiting.filter(t=>cs.items?.[t.id]?.status!=='queued');
 const hasBio=t=>!!(t.profile?.bio||'').trim();
 if(CAMPAIGN.mode===null||(CAMPAIGN.mode==='auto'&&!live))CAMPAIGN.mode=live?'auto':'draft';
 if(!CAMPAIGN.profile||!profiles[CAMPAIGN.profile])CAMPAIGN.profile=cs.default_profile||'balanced';
 const pickable=t=>!CAMPAIGN.bio||hasBio(t);
 if(CAMPAIGN.sel===null)CAMPAIGN.sel=new Set(eligible.filter(t=>pickable(t)&&!cs.items?.[t.id]).slice(0,Math.min(free,eligible.length)).map(t=>t.id));
 CAMPAIGN.sel=new Set([...CAMPAIGN.sel].filter(id=>{let t=eligible.find(x=>x.id===id);return t&&pickable(t)}));
 const redraw=()=>fillCampaign(p);
 p.append(el('p','','Agent napisze pierwszą wiadomość do wybranych nowych dopasowań, nawiązując do tego, co mają w opisie. Do osób, które już coś napisały, nic nie wysyła.'));
 if(CAMPAIGN.msg)p.append(el('div','callout ok',CAMPAIGN.msg));
 /* trwa / wynik */
 const done=Object.values(counts).reduce((a,b)=>a+b,0);
 if(done){let box=el('div','scard');box.append(el('div','glabel',cs.running?'Automatyzacja trwa':'Ostatnia automatyzacja'));
  let parts=[['sent','Wysłano'],['review','Szkice do wysłania'],['queued','W kolejce'],['started','Rozmowy rozpoczęte'],['skipped','Pominięto'],['failed','Nie udało się']].filter(([k])=>counts[k]).map(([k,l])=>l+': '+counts[k]);
  box.append(el('div','gdesc',parts.join(' · ')));
  let notes=Object.entries(cs.items||{}).filter(([,v])=>['skipped','failed'].includes(v.status)&&v.note);
  for(let [id,v] of notes.slice(0,6)){let th=data.threads.find(x=>x.id===id);box.append(el('div','gdesc',(th?th.display_name:'?')+': '+v.note))}
  let row=el('div','btnrow');
  if(counts.review){let q=el('button','primary','Przejrzyj szkice po kolei ('+counts.review+')');q.onclick=()=>{closePanel();showQueue()};row.append(q)}
  if(cs.running){let st=el('button','secondary danger','Zatrzymaj automatyzację');st.onclick=async()=>{if(!confirm('Zatrzymać automatyzację? To, co już wysłano, zostaje. Reszta kolejki zostanie odwołana.'))return;st.disabled=true;try{await api('/api/campaigns/stop','POST');await refresh();redraw()}catch(e){st.disabled=false}};row.append(st)}
  if(row.children.length)box.append(row);p.append(box)}
 if(!data.llm_enabled){p.append(el('div','callout warn','Podłącz model AI w ustawieniach serwera, żeby agent mógł pisać pierwsze wiadomości.'));return}
 if(!eligible.length){p.append(el('div','roster-empty','Nie ma teraz nowych dopasowań bez wiadomości. Gdy pojawią się nowe, wrócisz tu i klikniesz Start.'));return}
 {let c=tinderConn();if(c&&c.enabled&&c.blocked_until>Date.now()/1000)p.append(el('div','callout warn','Tinder jest chwilowo wstrzymany do '+clockText(c.blocked_until)+'. Szkice powstają normalnie, a wysyłka ruszy po przerwie.'))}
 /* 1. kogo */
 let head=el('div','row cmphead');p.append(el('div','cmpstep','1. Kogo'));
 let bioRow=el('label','cmpopt');let bioIn=el('input','');bioIn.type='checkbox';bioIn.checked=CAMPAIGN.bio;bioIn.onchange=()=>{CAMPAIGN.bio=bioIn.checked;CAMPAIGN.sel=null;redraw()};
 bioRow.append(bioIn,document.createTextNode(' Tylko osoby z opisem (agent ma wtedy do czego się odnieść)'));p.append(bioRow);
 let cap=Math.min(free,eligible.filter(pickable).length);
 let all=el('label','cmpopt');let allIn=el('input','');allIn.type='checkbox';allIn.checked=CAMPAIGN.sel.size>0&&CAMPAIGN.sel.size>=cap;
 allIn.onchange=()=>{CAMPAIGN.sel=allIn.checked?new Set(eligible.filter(pickable).slice(0,cap).map(t=>t.id)):new Set();redraw()};
 all.append(allIn,document.createTextNode(' Zaznacz wszystkich ('+cap+')'));
 head.append(all,el('span','gdesc','Wybrano '+CAMPAIGN.sel.size+' z '+eligible.length+(cs.free_slots!=null?' · wolnych miejsc w pakiecie: '+cs.free_slots:'')));p.append(head);
 let list=el('div','cmplist');
 for(let t of eligible){let it=cs.items?.[t.id];let ok=pickable(t);let r=el('label','cmprow'+(ok?'':' off'));let cb=el('input','');cb.type='checkbox';cb.checked=CAMPAIGN.sel.has(t.id);cb.disabled=!ok;
  cb.onchange=()=>{if(cb.checked&&CAMPAIGN.sel.size>=free){cb.checked=false;note.textContent='Pakiet '+data.plan.label+' ma wolnych miejsc: '+cs.free_slots+'.';return}cb.checked?CAMPAIGN.sel.add(t.id):CAMPAIGN.sel.delete(t.id);redraw()};
  let who=el('div','cmpwho');who.append(el('b','',t.display_name+(t.profile?.age?', '+t.profile.age:'')),el('span','muted',hasBio(t)?t.profile.bio.slice(0,90):'brak opisu: otwarcie byłoby ogólne'));
  r.append(cb,avatarFor(t,'queue'),who);if(it)r.append(el('span','qchip',CMP_STATUS[it.status]||it.status));list.append(r)}
 p.append(list);let note=el('div','mresult');p.append(note);
 /* 2. jak */
 p.append(el('div','cmpstep','2. Jak'));
 let modes=el('div','presets');
 const modeBtn=(key,label,off)=>{let b=el('button','chipbtn'+(CAMPAIGN.mode===key?' on':''),label);b.type='button';b.disabled=!!off;b.onclick=()=>{CAMPAIGN.mode=key;redraw()};return b};
 modes.append(modeBtn('auto','Agent wysyła sam',!live),modeBtn('draft','Szkice dla mnie'));p.append(group('Kto pisze pierwszy',CAMPAIGN.mode==='auto'?'Agent napisze i wyśle sam, po jednej wiadomości.':'Agent przygotuje szkice. Nic nie wyjdzie bez Twojego kliknięcia.',modes));
 if(!live){let w=el('div','callout warn',autoWhy());if(!(data.plan&&!data.plan.autopilot)){let b=el('button','linkish','Włącz autopilota →');b.onclick=()=>{closePanel();showAutopilot()};w.append(document.createTextNode(' '),b)}p.append(w)}
 const pf=profiles[CAMPAIGN.profile]||{};
 if(CAMPAIGN.mode==='auto'){
  let tempo=el('div','presets');for(let [k,v] of Object.entries(profiles)){let b=el('button','chipbtn'+(CAMPAIGN.profile===k?' on':''),v.label);b.type='button';b.onclick=()=>{CAMPAIGN.profile=k;CAMPAIGN.win=null;redraw()};tempo.append(b)}
  p.append(group('Tempo',pf.hint||'',tempo));
  /* godziny: własne, z podpowiedzią z Twoich rozmów */
  const bh=cs.best_hours||{n:0};const base=pf.window||['00:00','23:59'];
  if(!CAMPAIGN.win)CAMPAIGN.win=[...base];
  if(cs.window_locked){p.append(el('div','gdesc','Godziny wysyłki ustawił administrator: '+(pf.window?pf.window[0]+'–'+pf.window[1]:'bez ograniczeń')+'.'))}
  else{let hrs=el('div','cmphours');for(let [i,l] of [[0,'Od'],[1,'Do']]){let lab=el('label','');lab.append(document.createTextNode(l+' '));let inp=el('input','inp');inp.type='time';inp.value=CAMPAIGN.win[i];inp.onchange=()=>{if(inp.value){CAMPAIGN.win[i]=inp.value;redraw()}};lab.append(inp);hrs.append(lab)}
   let reset=el('button','linkish','Wróć do godzin profilu');reset.type='button';reset.onclick=()=>{CAMPAIGN.win=null;redraw()};hrs.append(reset);
   p.append(group('Godziny wysyłki','Wiadomości wychodzą tylko w tych godzinach ('+(cs.timezone||'Europe/Warsaw')+'). Poza nimi czekają do następnego dnia.',hrs));
   if(bh.window){let s=el('div','callout ok');s.append(document.createTextNode('Na podstawie '+bh.n+' odpowiedzi w Twoich rozmowach najczęściej odpisują między '+bh.window[0]+' a '+bh.window[1]+' ('+Math.round(100*bh.share)+'% odpowiedzi). '));
    let use=el('button','linkish','Użyj tych godzin');use.type='button';use.onclick=()=>{CAMPAIGN.win=[...bh.window];redraw()};s.append(use);p.append(s)}
   else p.append(el('div','gdesc',bh.n?'Podpowiedź godzin pojawi się, gdy będziesz mieć co najmniej 10 odpowiedzi w rozmowach (teraz: '+bh.n+'). Na start rozsądny jest wieczór.':'Podpowiedź godzin pojawi się, gdy ludzie zaczną odpisywać (potrzeba co najmniej 10 odpowiedzi).'))}}
 /* 3. podsumowanie */
 let n=CAMPAIGN.sel.size;p.append(el('div','cmpstep','3. Podsumowanie'));
 let sum=el('div','cmpsum');
 if(CAMPAIGN.mode==='auto'&&pf.gap_seconds!==undefined){
  const ew=cs.window_locked?pf.window:CAMPAIGN.win;const win=ew?(()=>{let [a,b]=ew.map(x=>{let [h,m]=x.split(':');return +h+m/60});return (b>a?b-a:24-a+b)*3600})():86400;
  const perDay=Math.max(1,Math.min(pf.per_day||n,Math.floor(win/Math.max(1,pf.gap_seconds))));const days=Math.max(1,Math.ceil(n/perDay));
  sum.append(el('div','',(n?'Wysyłka '+n+' '+pl(n,'wiadomość','wiadomości','wiadomości'):'Zaznacz osoby powyżej')+(n?(days===1?', skończy się dziś (jeśli zaczniesz w oknie).':', rozłożona na około '+days+' '+pl(days,'dzień','dni','dni')+'.'):'.')),
   el('div','muted','Co '+fmtDur(pf.gap_seconds)+', do '+pf.per_day+' dziennie'+(ew?', w godzinach '+ew[0]+'–'+ew[1]:'')+' ('+(cs.timezone||'Europe/Warsaw')+'). '+(cs.reserve||0)+' wysyłek na godzinę zostaje na odpowiedzi.'))}
 else sum.append(el('div','',n?'Przygotuję '+n+' '+pl(n,'szkic','szkice','szkiców')+'. Wyślesz je po kolei jednym przyciskiem.':'Zaznacz osoby powyżej.'));
 p.append(sum);
 let go=el('button','primary','Start · '+n+' '+pl(n,'osoba','osoby','osób'));go.disabled=!n;
 go.onclick=async()=>{go.disabled=true;note.className='mresult';note.textContent='Uruchamiam…';
  try{let r=await api('/api/campaigns','POST',{thread_ids:[...CAMPAIGN.sel],mode:CAMPAIGN.mode,profile:CAMPAIGN.profile,only_with_bio:CAMPAIGN.bio,...(CAMPAIGN.mode==='auto'&&CAMPAIGN.win&&!cs.window_locked?{window_start:CAMPAIGN.win[0],window_end:CAMPAIGN.win[1]}:{})});CAMPAIGN.sel=null;let rej=Object.values(r.rejected||{});
   CAMPAIGN.msg='Ruszyło: '+r.accepted.length+(rej.length?'. Pominięto '+rej.length+': '+rej[0]:'.');await refresh();redraw()}
  catch(e){note.className='mresult err';note.textContent=ERR_PL[e.message]||e.message;go.disabled=false}};
 let foot=el('div','mfoot');foot.append(go);p.append(foot)}

/* ---------- Automatyzacje: lista rund z wynikami (wzór: lista subskrypcji w Stripe) ---------- */
const AUTO={tab:'active'};
const ROUND_STATUS={active:'Aktywna',done:'Zakończona',stopped:'Zatrzymana'};
const PERSON_STATUS={queued:'W kolejce',review:'Szkic czeka na Ciebie',sent:'Wysłano, czeka na odpowiedź',replied:'Odpisała',talking:'Rozmawiacie',date:'Spotkanie',skipped:'Pominięto',failed:'Nie udało się'};
const pct=(a,b)=>b?Math.round(100*a/b)+'%':'–';
function roundWhen(c){let d=new Date(c);return isNaN(d)?'':d.toLocaleDateString('pl-PL',{day:'numeric',month:'numeric'})+' '+d.toLocaleTimeString('pl-PL',{hour:'2-digit',minute:'2-digit'})}
function renderAuto(){const box=document.getElementById('auto-view');if(!box||!data)return;box.replaceChildren();
 const rounds=(data.campaign&&data.campaign.rounds)||[];const wrap=el('div','autolist');
 const head=el('div','autohead');head.append(el('h2','','Automatyzacje'));const nb=el('button','primary','Nowa automatyzacja');nb.onclick=showCampaign;head.append(nb);wrap.append(head);
 const tabs=[['active','Aktywne',rounds.filter(r=>r.status==='active').length],['done','Zakończone',rounds.filter(r=>r.status!=='active').length],['all','Wszystkie',rounds.length]];
 const st=el('div','autostat');for(let [k,l,n] of tabs){let b=el('button',AUTO.tab===k?'on':'',l);b.append(el('span','',n));b.onclick=()=>{AUTO.tab=k;renderAuto()};st.append(b)}wrap.append(st);
 const shown=rounds.filter(r=>AUTO.tab==='all'||(AUTO.tab==='active'?r.status==='active':r.status!=='active'));
 if(!shown.length){let e=el('div','roster-empty',rounds.length?'Nie ma tu nic w tej zakładce.':'Jeszcze nie uruchomiono żadnej automatyzacji. Kliknij „Nowa automatyzacja”, żeby agent zagadał do nowych dopasowań.');wrap.append(e)}
 else{const tb=el('table','autotable');const th=el('tr');for(let [l,c] of [['Nazwa',''],['Status',''],['Osoby',''],['Wysłano',''],['Odpisały',''],['Rozmowy 5+','hide-sm'],['Umówieni','hide-sm'],['Start','hide-sm']]){let x=el('th',c,l);th.append(x)}tb.append(th);
  for(let r of shown){let tr=el('tr','arow');tr.tabIndex=0;const go=()=>showRound(r.id);tr.onclick=go;tr.onkeydown=e=>{if(e.key==='Enter')go()};
   let nm=el('td','');nm.append(el('b','',r.name));let st=el('td','');st.append(el('span','sbadge '+r.status,ROUND_STATUS[r.status]||r.status));
   tr.append(nm,st,el('td','',r.total),el('td','',r.sent+' / '+r.total),el('td','',r.replied+' ('+pct(r.replied,r.sent)+')'),el('td','hide-sm',r.talking),el('td','hide-sm',r.dates),el('td','hide-sm',roundWhen(r.created)));tb.append(tr)}wrap.append(tb)}
 const waiting=data.threads.filter(t=>t.state==='new_match').length;
 if(waiting){const hints=el('div','autohints');const a=el('div','hint');a.append(el('b','','Zagadaj nowe dopasowania'),document.createTextNode(waiting+' '+pl(waiting,'osoba czeka','osoby czekają','osób czeka')+' na pierwszą wiadomość.'));const bt=el('button','linkish','Nowa automatyzacja →');bt.onclick=showCampaign;a.append(el('div','',''),bt);hints.append(a);wrap.append(hints)}
 box.append(wrap)}
function showRound(id){const r=((data.campaign&&data.campaign.rounds)||[]).find(x=>x.id===id);if(!r)return;const p=panel(r.name+' · '+(ROUND_STATUS[r.status]||r.status));
 const prof=(data.campaign.profiles||{})[r.profile];
 p.append(el('p','gdesc',(r.mode==='auto'?'Agent wysyłał sam':'Szkice dla Ciebie')+(r.mode==='auto'&&prof?' · tempo '+prof.label:'')+(r.mode==='auto'&&(r.window||(prof&&prof.window))?' · godziny '+(r.window||prof.window).join('–'):'')+' · start '+roundWhen(r.created)));
 const tiles=el('div','scard');tiles.append(el('div','gdesc','Wysłano: '+r.sent+' / '+r.total+' · Odpisały: '+r.replied+' ('+pct(r.replied,r.sent)+') · Rozmowy 5+: '+r.talking+' · Spotkania: '+r.dates));p.append(tiles);
 if(r.status==='active'){let stop=el('button','secondary danger','Zatrzymaj automatyzację');stop.onclick=async()=>{if(!confirm('Zatrzymać automatyzację? To, co już wysłano, zostaje. Reszta kolejki zostanie odwołana.'))return;stop.disabled=true;try{await api('/api/campaigns/stop','POST');await refresh();showRound(id)}catch(e){stop.disabled=false}};p.append(stop)}
 const list=el('div','cmplist');for(let x of r.people){let row=el('div','cmprow');let th=data.threads.find(t=>t.id===x.thread_id);
  let who=el('div','cmpwho');who.append(el('b','',x.name),el('span','muted',x.note||(x.messages?x.messages+' '+pl(x.messages,'wiadomość','wiadomości','wiadomości'):'')));
  if(th)row.append(avatarFor(th,'queue'));row.append(who,el('span','pstat '+x.status,PERSON_STATUS[x.status]||x.status));
  if(th){row.style.cursor='pointer';row.onclick=()=>{closePanel();setView('chats');choose(th.id)}}list.append(row)}p.append(list)}
