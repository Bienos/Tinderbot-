const form=document.getElementById('waitlist'),result=document.getElementById('form-result');
form.addEventListener('submit',async e=>{e.preventDefault();const f=new FormData(form);result.className='';result.textContent='Wysyłam...';
const payload={email:f.get('email'),name:f.get('name'),mode:f.get('mode'),website:f.get('website'),adult:f.get('adult')==='on',terms:f.get('terms')==='on',marketing:f.get('marketing')==='on'};
try{const r=await fetch('/api/waitlist',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});const b=await r.json().catch(()=>({}));
if(!r.ok)throw new Error(b.detail||'Coś poszło nie tak. Spróbuj ponownie.');result.className='ok';result.textContent='Zapisano do bety. Odezwiemy się mailowo, gdy zwolni się miejsce.';form.reset()}
catch(err){result.className='err';result.textContent=err.message}});
