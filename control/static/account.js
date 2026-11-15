async function post(url,payload){const r=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload||{})});const b=await r.json().catch(()=>({}));if(!r.ok)throw new Error(b.detail||'Coś poszło nie tak. Spróbuj ponownie.');return b}
function bind(id,url,build,done){const f=document.getElementById(id);if(!f)return;const out=f.querySelector('[role=status]');
f.addEventListener('submit',async e=>{e.preventDefault();const btn=f.querySelector('button[type=submit]');btn.disabled=true;out.className='';out.textContent='Chwila...';
try{await post(url,build(new FormData(f)));done()}catch(err){out.className='err';out.textContent=err.message;btn.disabled=false}})}
bind('login-form','/api/login',f=>({email:f.get('email'),password:f.get('password')}),()=>location.href='/konto');
bind('register-form','/api/register',f=>({email:f.get('email'),name:f.get('name'),password:f.get('password'),mode:f.get('mode'),website:f.get('website'),adult:f.get('adult')==='on',terms:f.get('terms')==='on',marketing:f.get('marketing')==='on'}),()=>location.href='/konto');
bind('forgot-form','/api/password/forgot',f=>({email:f.get('email')}),()=>{const out=document.querySelector('#forgot-form [role=status]');out.className='ok';out.textContent='Jeśli to konto istnieje, link jest już w drodze. Sprawdź też spam.';document.querySelector('#forgot-form button[type=submit]').disabled=true});
bind('reset-form','/api/password/reset',f=>({password:f.get('password'),token:new URLSearchParams(location.search).get('t')||''}),()=>location.href='/konto');
bind('delete-form','/api/account/delete',f=>({password:f.get('password')}),()=>location.href='/');
const logout=document.getElementById('logout');if(logout)logout.addEventListener('click',async()=>{await post('/api/logout').catch(()=>{});location.href='/'});
const card=document.getElementById('status-card');
function btn(text,cls,onclick,href){const b=document.createElement(href?'a':'button');b.className=cls;b.textContent=text;if(href)b.href=href;else{b.type='button';b.onclick=onclick}return b}
async function go(url){try{const r=await post(url);location.href=r.url}catch(e){const p=document.createElement('p');p.className='err';p.textContent=e.message;card.append(p)}}
if(card){fetch('/api/me').then(r=>r.ok?r.json():Promise.reject()).then(me=>{document.getElementById('hello').textContent=me.name?'Cześć, '+me.name:me.email;
 const h=document.createElement('h1'),p=document.createElement('p');card.append(h,p);const paidNow=new URLSearchParams(location.search).get('platnosc')==='ok';
 const steps=document.getElementById('steps');const mark=n=>{if(steps)[...steps.children].forEach((li,i)=>li.classList.toggle('done',i<n))};
 if(me.status==='disabled'){h.textContent='Konto jest wyłączone';p.textContent='Skontaktuj się z nami, jeśli to pomyłka.';mark(0);return}
 if(me.panel_ready){mark(2);h.textContent='Twój panel jest gotowy';p.textContent='Otwórz panel i połącz konto Tinder. Zalogujemy Cię automatycznie.';card.append(btn('Otwórz mój panel','btn',null,'/konto/panel'))}
 else if(me.billing_enabled&&!me.has_access&&!paidNow){mark(1);
  if(me.plan_status==='canceled'){h.textContent='Subskrypcja jest anulowana';p.textContent='Wznów, żeby wrócić do panelu. Twoje ustawienia czekają.';card.append(btn('Wznów subskrypcję','btn',()=>go('/api/billing/checkout')))}
  else if(me.plan_status==='past_due'||me.plan_status==='unpaid'){h.textContent='Płatność się nie powiodła';p.textContent='Zaktualizuj kartę, żeby nie stracić dostępu.';card.append(btn('Zaktualizuj płatność','btn',()=>go('/api/billing/portal')))}
  else{h.textContent='Jeszcze jeden krok';p.textContent='Wykup dostęp, a my przygotujemy Twój osobny serwer. Płatność obsługuje Stripe, anulujesz w każdej chwili.';card.append(btn('Wykup dostęp','btn',()=>go('/api/billing/checkout')))}}
 else if(me.provision_state==='failed'){mark(2);h.textContent='Stawianie serwera się przedłuża';p.textContent='Coś poszło nie tak przy przygotowaniu Twojego serwera. Już nad tym pracujemy i napiszemy, gdy będzie gotowy.'}
 else{mark(2);h.textContent=paidNow?'Płatność przyjęta. Dziękujemy!':'Przygotowujemy Twój serwer';p.textContent=me.provision_state==='running'?'Stawiamy Twój osobny serwer. To zwykle trwa kilka minut; odśwież stronę za chwilę.':'Stawiamy Twój osobny serwer. Napiszemy mailem, gdy panel będzie gotowy.';const s=document.createElement('div');s.className='queue';s.innerHTML='<span></span><span></span><span></span>';card.append(s)}
 if(me.can_manage_billing)card.append(btn('Zarządzaj subskrypcją','linkbtn',()=>go('/api/billing/portal')));
}).catch(()=>location.href='/zaloguj')}
document.querySelectorAll('[data-toggle=password]').forEach(b=>b.addEventListener('click',()=>{const i=b.previousElementSibling;const show=i.type==='password';i.type=show?'text':'password';b.textContent=show?'Ukryj':'Pokaż'}));
