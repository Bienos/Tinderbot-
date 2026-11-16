const _wp=new URLSearchParams(location.search).get('plan');if(_wp)try{sessionStorage.setItem('winq-plan',_wp)}catch(e){}
async function post(url,payload){const r=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload||{})});const b=await r.json().catch(()=>({}));if(!r.ok)throw new Error(b.detail||'Coś poszło nie tak. Spróbuj ponownie.');return b}
function bind(id,url,build,done){const f=document.getElementById(id);if(!f)return;const out=f.querySelector('[role=status]');
f.addEventListener('submit',async e=>{e.preventDefault();const btn=f.querySelector('button[type=submit]');btn.disabled=true;out.className='';out.textContent='Chwila...';
try{await post(url,build(new FormData(f)));done()}catch(err){out.className='err';out.textContent=err.message;btn.disabled=false}})}
bind('login-form','/api/login',f=>({email:f.get('email'),password:f.get('password')}),()=>{const nx=new URLSearchParams(location.search).get('next');location.href=nx==='/konto/panel?view=stats'?nx:'/konto'});  // the weekly e-mail link: after signing in, straight to the statistics
bind('register-form','/api/register',f=>({email:f.get('email'),name:f.get('name'),password:f.get('password'),source:f.get('source')||'',website:f.get('website'),adult:f.get('adult')==='on',terms:f.get('terms')==='on',marketing:f.get('marketing')==='on'}),()=>location.href='/konto');
bind('forgot-form','/api/password/forgot',f=>({email:f.get('email')}),()=>{const out=document.querySelector('#forgot-form [role=status]');out.className='ok';out.textContent='Link jest już w drodze. Sprawdź skrzynkę, także spam.';document.querySelector('#forgot-form button[type=submit]').disabled=true});
bind('reset-form','/api/password/reset',f=>({password:f.get('password'),token:new URLSearchParams(location.search).get('t')||''}),()=>location.href='/konto');
bind('delete-form','/api/account/delete',f=>({password:f.get('password')}),()=>location.href='/');
const logout=document.getElementById('logout');if(logout)logout.addEventListener('click',async()=>{await post('/api/logout').catch(()=>{});location.href='/'});
const card=document.getElementById('status-card');
function btn(text,cls,onclick,href){const b=document.createElement(href?'a':'button');b.className=cls;b.textContent=text;if(href)b.href=href;else{b.type='button';b.onclick=onclick}return b}
async function go(url,payload){try{const r=await post(url,payload);location.href=r.url}catch(e){const p=document.createElement('p');p.className='err';p.textContent=e.message;card.append(p)}}
function buy(label,plans,trial){const l=document.createElement('label');l.className='check consent';const c=document.createElement('input');c.type='checkbox';
 l.append(c,document.createTextNode(' Akceptuję regulamin i proszę o rozpoczęcie usługi od razu, przed upływem 14 dni na odstąpienie. Jeśli odstąpię, zapłacę tylko za dni korzystania.'));
 if(plans&&plans.length){const want=(()=>{try{return sessionStorage.getItem('winq-plan')||''}catch(e){return ''}})(),box=document.createElement('div');box.className='plans';
  const keys=(plans[0].periods||[]).map(x=>x.key),wp=(()=>{try{return sessionStorage.getItem('winq-period')||''}catch(e){return ''}})();let per=keys.includes(wp)?wp:(keys.includes('12')?'12':'1');
  const zl=n=>(Number.isInteger(n)?String(n):n.toFixed(2).replace('.',','))+' zł',free=n=>n===1?'1 miesiąc gratis':n+' miesiące gratis';
  const start=(slug)=>{if(!c.checked){l.classList.add('need');l.scrollIntoView({block:'center'});return}go('/api/billing/checkout',{start_now:true,plan:slug,period:per})};
  const draw=()=>{box.replaceChildren();
   if(keys.length>1){const sw=document.createElement('div');sw.className='period acc';plans[0].periods.forEach(x=>{const b=document.createElement('button');b.type='button';b.className=x.key===per?'on':'';b.textContent=x.label+(x.free?' · '+free(x.free):'');b.onclick=()=>{per=x.key;try{sessionStorage.setItem('winq-period',per)}catch(e){}draw()};sw.append(b)});box.append(sw)}
   if(trial&&per===trial.period){const tn=document.createElement('p');tn.className='tier-trialtag';tn.textContent='Pierwsze '+trial.text+' za darmo';box.append(tn)}
   plans.forEach(p=>{const f=(p.periods||[]).find(x=>x.key===per)||p.periods[0],o=document.createElement('div');o.className='plan-opt'+((want?want===p.slug:p.popular)?' pick':'');
    const h=document.createElement('h3');h.textContent=p.name;const pr=document.createElement('small');pr.textContent=zl(f.per_month)+' / mies.';h.append(pr);
    const d=document.createElement('p');d.textContent=p.tagline+'. '+(p.autopilot?'Odpowiada za Ciebie, ':'Szkice odpowiedzi, ')+'do '+p.conversations+' aktywnych rozmów naraz.';
    o.append(h,d,btn('Wybieram '+p.name,p.popular||want===p.slug?'btn':'btn ghost',()=>start(p.slug)));box.append(o)})};
  draw();card.append(box,l);return}
 const b=btn(label,'btn',()=>{if(!c.checked){l.classList.add('need');return}go('/api/billing/checkout',{start_now:true})});card.append(l,b)}
function withdrawBox(host){const d=document.createElement('details');d.className='withdraw';d.open=true;const s=document.createElement('summary');s.textContent='Odstąp od umowy';
 const t=document.createElement('p');t.textContent='Masz 14 dni od zakupu. Nie musisz podawać powodu. Zwrócimy pieniądze pomniejszone o dni korzystania, w ciągu 14 dni.';
 const b=btn('Potwierdzam odstąpienie od umowy','btn ghost',async()=>{b.disabled=true;try{await post('/api/billing/withdraw',{confirm:true});t.textContent='Gotowe. Potwierdzenie wysłaliśmy mailem.';b.remove()}catch(e){t.textContent=e.message;b.disabled=false}});
 d.append(s,t,b);host.append(d)}
// Setup progress: real stages from the server, an honest estimate and a running clock.
const STAGES=[['pay','Płatność potwierdzona'],['creating','Tworzymy Twój osobny serwer'],['building','Instalujemy asystenta'],['starting','Uruchamiamy i sprawdzamy'],['ready','Gotowe, otwieramy panel']];
const ORDER={payment:0,queued:1,manual:1,creating:1,building:2,starting:3,ready:4,slow:2};
const fmt=s=>Math.floor(s/60)+':'+String(Math.floor(s%60)).padStart(2,'0');
function progress(me,paidNow){const card=document.getElementById('status-card'),setup=me.setup||{stage:'queued',expected:240,elapsed:0};
 const stage=!me.has_access?'payment':setup.stage,at=ORDER[stage]??1,expected=setup.expected||240,mins=Math.round(expected/60);
 const live=['creating','building','starting'].includes(stage)||(stage==='queued'&&(paidNow||setup.elapsed>0));
 const h=card.querySelector('h1'),p=card.querySelector('p');
 h.textContent=stage==='payment'?'Potwierdzamy płatność':paidNow&&at<2?'Płatność przyjęta. Dziękujemy!':'Przygotowujemy Twój serwer';
 p.textContent=stage==='payment'?'Stripe potwierdza płatność. To zwykle kilka sekund.':
  stage==='slow'?'Trwa to dłużej niż zwykle. Pracujemy nad tym i napiszemy mailem, gdy panel będzie gotowy.':
  stage==='queued'&&!live?'Przygotujemy Twój serwer i napiszemy mailem, gdy panel będzie gotowy. Ta strona odświeży się sama.':
  stage==='manual'?'Uruchamiamy Twój serwer ręcznie. Napiszemy mailem, gdy panel będzie gotowy, zwykle w ciągu kilku godzin.':
  'Stawiamy osobny serwer tylko dla Ciebie. Zwykle trwa to '+Math.max(1,mins-1)+'–'+(mins+1)+(mins+1>=5?' minut':' minuty')+'. Ta strona odświeży się sama.';
 const box=document.createElement('div');box.className='setup';
 const bar=document.createElement('div');bar.className='setup-bar';bar.setAttribute('role','progressbar');bar.setAttribute('aria-label','Postęp przygotowania serwera');
 const fill=document.createElement('span');bar.append(fill);
 const meta=document.createElement('p');meta.className='setup-meta';
 const list=document.createElement('ol');list.className='setup-steps';
 STAGES.forEach(([k,label],i)=>{const li=document.createElement('li');li.textContent=label;
  li.className=i<at||(k==='pay'&&me.has_access)?'done':i===at?(stage==='slow'?'now slow':'now'):'';list.append(li)});
 box.append(bar,meta,list);card.append(box);
 const t0=Date.now()-1000*(setup.elapsed||0);
 const floor=[3,8,30,70,100][at],ceil=[8,30,70,96,100][at];
 const draw=()=>{const el=(Date.now()-t0)/1000,timePct=Math.min(96,el/expected*100);
  const pct=live?Math.max(floor,Math.min(ceil,timePct)):floor;fill.style.width=pct+'%';bar.setAttribute('aria-valuenow',String(Math.round(pct)));
  if(!live){meta.textContent='';return}
  const left=expected-el;meta.textContent='Minęło '+fmt(el)+' · '+(left>20?'zostało około '+Math.ceil(left/60)+' min':'jeszcze chwila, kończymy');};
 draw();if(live)setInterval(draw,1000);watch(me)}
// While the server is being prepared, check again every few seconds and redraw as soon as anything changes.
function watch(was){const key=m=>[m.panel_ready,m.provision_state,m.has_access,m.status,(m.setup||{}).stage].join('|'),start=Date.now();
 const tick=()=>{if(Date.now()-start>15*60e3)return;fetch('/api/me',{cache:'no-store'}).then(r=>r.ok?r.json():null).then(me=>{
  if(me&&key(me)!==key(was))location.reload();else setTimeout(tick,4000)}).catch(()=>setTimeout(tick,8000))};
 setTimeout(tick,4000)}
if(card){fetch('/api/me').then(r=>r.ok?r.json():Promise.reject()).then(me=>{document.getElementById('hello').textContent=me.name?'Cześć, '+me.name:me.email;
 const h=document.createElement('h1'),p=document.createElement('p');card.append(h,p);const paidNow=new URLSearchParams(location.search).get('platnosc')==='ok';
 const steps=document.getElementById('steps');const mark=n=>{if(steps)[...steps.children].forEach((li,i)=>li.classList.toggle('done',i<n))};
 if(me.status==='disabled'){h.textContent='Konto jest wyłączone';p.textContent='Skontaktuj się z nami, jeśli to pomyłka.';mark(0);return}
 const st=(me.setup||{}).stage;
 if(me.panel_ready&&!['building','starting','creating'].includes(st)){mark(2);h.textContent='Twój panel jest gotowy';p.textContent='Otwórz panel i połącz konto Tinder. Zalogujemy Cię automatycznie.';card.append(btn('Otwórz mój panel','btn',null,'/konto/panel'))}
 else if(me.billing_enabled&&!me.has_access&&!paidNow){mark(1);
  if(me.plan_status==='canceled'){h.textContent='Subskrypcja jest anulowana';p.textContent='Wznów, żeby wrócić do panelu. Twoje ustawienia czekają.';buy('Wznów subskrypcję')}
  else if(me.plan_status==='past_due'||me.plan_status==='unpaid'){h.textContent='Płatność się nie powiodła';p.textContent='Zaktualizuj kartę, żeby nie stracić dostępu.';card.append(btn('Zaktualizuj płatność','btn',()=>go('/api/billing/portal')))}
  else{h.textContent='Jeszcze jeden krok';const tr=me.trial_days||0,td=tr===1?'1 dzień':tr+' dni',many=!!(me.plans&&me.plans.length);p.textContent=many?'Wybierz pakiet, a my przygotujemy Twój osobny serwer. '+(tr?'W pakiecie rocznym pierwsze '+td+' za darmo: kartę podajesz od razu, a jeśli anulujesz przed końcem okresu próbnego, nic nie zapłacisz. ':'')+'Płatność obsługuje Stripe.':'Wykup dostęp, a my przygotujemy Twój osobny serwer. Płatność obsługuje Stripe, anulujesz w każdej chwili.';buy('Wykup dostęp',me.plans,tr?{period:me.trial_period||'12',text:td}:null)}}
 else if(me.has_access||paidNow){mark(2);progress(me,paidNow)}
 else if(me.provision_state==='failed'){mark(2);h.textContent='Stawianie serwera się przedłuża';p.textContent='Coś poszło nie tak przy przygotowaniu Twojego serwera. Już nad tym pracujemy i napiszemy, gdy będzie gotowy.'}
 else{mark(2);h.textContent=paidNow?'Płatność przyjęta. Dziękujemy!':'Przygotowujemy Twój serwer';p.textContent=me.provision_state==='running'?'Stawiamy Twój osobny serwer. To zwykle trwa kilka minut, a ta strona odświeży się sama.':'Stawiamy Twój osobny serwer. Ta strona odświeży się sama, a gdy panel będzie gotowy, napiszemy też mailem.';const s=document.createElement('div');s.className='queue';s.innerHTML='<span></span><span></span><span></span>';card.append(s);watch(me)}
 if(me.withdrawn){const w=document.createElement('p');w.className='muted';w.textContent='Odstąpiłeś od umowy. Zwrot jest w drodze.';card.append(w)}
 if(me.plans&&me.plans.length&&me.plan){const cur=me.plans.find(x=>x.slug===me.plan);if(cur){const w=document.createElement('p');w.className='muted';const pp=(cur.periods||[]).find(x=>x.key===(me.plan_period||'1'));w.textContent='Twój pakiet to '+cur.name+(pp&&pp.months>1?' ('+pp.label.toLowerCase()+')':'')+', do '+cur.conversations+' aktywnych rozmów.';card.append(w)}}
 if(me.panel_ready){const lab=document.createElement('label');lab.className='muted weekly-pref';const cb=document.createElement('input');cb.type='checkbox';cb.checked=me.weekly_summary!==false;cb.addEventListener('change',()=>{cb.disabled=true;post('/api/account/weekly',{enabled:cb.checked}).catch(()=>{cb.checked=!cb.checked}).finally(()=>{cb.disabled=false})});lab.append(cb,document.createTextNode(' Cotygodniowe podsumowanie e-mailem (status i liczby, bez treści rozmów)'));card.append(lab)}
 if(me.can_manage_billing)card.append(btn(me.plans&&me.plans.length?'Zmień pakiet lub zarządzaj subskrypcją':'Zarządzaj subskrypcją','linkbtn',()=>go('/api/billing/portal')));
}).catch(()=>location.href='/zaloguj')}
document.querySelectorAll('[data-toggle=password]').forEach(b=>b.addEventListener('click',()=>{const i=b.previousElementSibling;const show=i.type==='password';i.type=show?'text':'password';b.textContent=show?'Ukryj':'Pokaż'}));

// Withdrawal from the contract lives with the other account actions (Zaawansowane ustawienia konta), not on the status page.
const withdrawZone=document.getElementById('withdraw-zone');
if(withdrawZone)fetch('/api/me').then(r=>r.ok?r.json():Promise.reject()).then(me=>{if(me.can_withdraw)withdrawBox(withdrawZone)}).catch(()=>{});
