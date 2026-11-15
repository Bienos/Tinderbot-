async function post(url,payload){const r=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload||{})});const b=await r.json().catch(()=>({}));if(!r.ok)throw new Error(b.detail||'Coś poszło nie tak. Spróbuj ponownie.');return b}
function bind(id,url,build,done){const f=document.getElementById(id);if(!f)return;const out=f.querySelector('[role=status]');
f.addEventListener('submit',async e=>{e.preventDefault();const btn=f.querySelector('button[type=submit]');btn.disabled=true;out.className='';out.textContent='Chwila...';
try{await post(url,build(new FormData(f)));done()}catch(err){out.className='err';out.textContent=err.message;btn.disabled=false}})}
bind('login-form','/api/login',f=>({email:f.get('email'),password:f.get('password')}),()=>location.href='/konto');
bind('register-form','/api/register',f=>({email:f.get('email'),name:f.get('name'),password:f.get('password'),mode:f.get('mode'),website:f.get('website'),adult:f.get('adult')==='on',terms:f.get('terms')==='on',marketing:f.get('marketing')==='on'}),()=>location.href='/konto');
bind('delete-form','/api/account/delete',f=>({password:f.get('password')}),()=>location.href='/');
const logout=document.getElementById('logout');if(logout)logout.addEventListener('click',async()=>{await post('/api/logout').catch(()=>{});location.href='/'});
const card=document.getElementById('status-card');
if(card){fetch('/api/me').then(r=>r.ok?r.json():Promise.reject()).then(me=>{document.getElementById('hello').textContent=me.name?'Cześć, '+me.name:me.email;
 const h=document.createElement('h1'),p=document.createElement('p');card.append(h,p);
 if(me.panel_ready){h.textContent='Twój panel jest gotowy';p.textContent='Otwórz panel, połącz konto randkowe i ustaw styl. Zalogujemy Cię automatycznie.';const a=document.createElement('a');a.className='btn';a.href='/konto/panel';a.textContent='Otwórz mój panel';card.append(a)}
 else if(me.status==='disabled'){h.textContent='Konto jest wyłączone';p.textContent='Skontaktuj się z nami, jeśli to pomyłka.'}
 else{h.textContent='Jesteś na liście bety';p.textContent='Przygotowujemy Twój osobny serwer. Napiszemy mailem, gdy panel będzie gotowy. Nie musisz nic robić.';const s=document.createElement('div');s.className='queue';s.innerHTML='<span></span><span></span><span></span>';card.append(s)}
}).catch(()=>location.href='/zaloguj')}
