"""Opt-in REAL Chromium tests. Never report fixture tests as browser tests."""
import asyncio,os,subprocess,time
from pathlib import Path
import httpx,pytest
pytestmark=pytest.mark.skipif(os.getenv('RUN_BROWSER_E2E')!='1',reason='Set RUN_BROWSER_E2E=1 after installing Chromium')
TOKEN='browser-test-token-at-least-thirty-two-characters'
BASE='http://127.0.0.1:8765'
@pytest.fixture
def server(tmp_path,monkeypatch):
    env={**os.environ,'AGENT_DB_PATH':str(tmp_path/'browser.db'),'WORKER_ENABLED':'true','WORKER_INTERVAL':'1',
         'PUBLIC_ORIGIN':'http://127.0.0.1:8765','DASHBOARD_TOKEN':TOKEN,'DATING_AGENT_SOURCE':'browser',
         'SEED_SIMULATOR':'true','COOKIE_SECURE':'false'}
    env.pop('OPENAI_API_KEY',None)
    env.pop('ANTHROPIC_API_KEY',None)
    env['TINDER_ENABLED']='false';env.pop('TINDER_AUTH_TOKEN',None)
    log=(tmp_path/'server.log').open('w')
    proc=subprocess.Popen([str(Path('.venv/bin/python').absolute()),'-m','uvicorn','app:app','--host','127.0.0.1','--port','8765','--no-access-log'],env=env,stdout=log,stderr=log)
    try:
        for _ in range(100):
            if proc.poll() is not None:pytest.fail((tmp_path/'server.log').read_text())
            try:
                if httpx.get(BASE+'/health').status_code==200:break
            except httpx.HTTPError:pass
            time.sleep(.1)
        else:pytest.fail('Server failed to start')
        monkeypatch.setenv('DASHBOARD_TOKEN',TOKEN)
        yield httpx.Client(base_url=BASE,headers={'Authorization':'Bearer '+TOKEN},timeout=30)
    finally:
        proc.terminate();proc.wait(timeout=10);log.close()

async def test_real_browser_discovery_dashboard_autonomous_and_stale(server,tmp_path):
    from playwright.async_api import async_playwright
    from agent.browser import read_mock_threads,send_mock_approved
    from agent.adapters import StaleAction
    remote=await read_mock_threads();assert len(remote)==7;assert remote['t4']==[]
    errors=[]
    async with async_playwright() as p:
        browser=await p.chromium.launch()
        page=await browser.new_page(extra_http_headers={'Authorization':'Bearer '+TOKEN})
        page.on('pageerror',lambda e:errors.append(str(e)))
        await page.goto(BASE)
        await page.locator('.thread').first.wait_for()
        await page.get_by_role('button',name='Settings',exact=True).click()
        tinder_button=page.get_by_role('button',name='Connect Tinder · automatic replies',exact=True)
        assert await tinder_button.is_disabled()
        await page.locator('select').select_option('simulation')
        await page.get_by_role('button',name='Save settings',exact=True).click()
        await page.locator('#panel').wait_for(state='hidden')
        # No sync click: the background worker discovers, drafts and sends using real Chromium.
        for _ in range(150):
            state=(await asyncio.to_thread(server.get,'/api/state')).json()
            if any(a['status']=='sent' for a in state['actions']):break
            await asyncio.sleep(.2)
        else:pytest.fail(str(state['worker']))
        actions=[a for a in state['actions'] if a['status']=='sent'];assert len(actions)==1
        d=next(d for d in state['drafts'] if d['thread_id']=='t1');assert d['status']=='sent'
        assert (await read_mock_threads())['t1'][-1]['sender']=='you'
        await page.evaluate('refresh()')
        await page.get_by_role('button',name='Activity',exact=True).click()
        await page.get_by_role('heading',name='Activity & reliability').wait_for()
        await page.screenshot(path=str(tmp_path/'dashboard.png'),full_page=True)
        assert not errors,errors
        await browser.close()
    # Source-side compare-and-send rejects an obsolete anchor in a real browser interaction.
    before=remote['t2'][-1]['id']
    server.post('/api/mock/threads/t2/incoming',json={'body':'nowa wiadomość'})
    with pytest.raises(StaleAction):await send_mock_approved('t2','older draft','stale-action',before)
    await asyncio.sleep(1.5)
    assert len([a for a in server.get('/api/state').json()['actions'] if a['status']=='sent'])==1

async def test_real_browser_lost_response_idempotency(server):
    from agent.browser import page_context
    before=(await asyncio.to_thread(server.get,'/api/mock/source')).json()['messages']['t1'][-1]['id']
    async with page_context() as page:
        await page.locator('[data-thread-button="t1"]').click()
        await page.locator('[data-chat-input]').fill('browser crash test')
        await page.locator('[data-chat-input]').evaluate('(e,a)=>{e.dataset.action="crash-action";e.dataset.anchor=a}',before)
        # Commit the server-side send, then crash the tab before the receipt reaches the DOM.
        crashed=asyncio.Event()
        async def drop_receipt(route):
            response=await route.fetch();assert response.ok
            await route.abort();await page.close();crashed.set()
        await page.route('**/api/mock/send',drop_receipt)
        await page.locator('[data-send-button]').click(timeout=5000)
        await asyncio.wait_for(crashed.wait(),10)
        assert page.is_closed()
    # Retrying the same action key returns the first receipt, never duplicates.
    r=server.post('/api/mock/send',json={'thread_id':'t1','body':'browser crash test','action_id':'crash-action','anchor':before})
    assert r.status_code==200
    data=server.get('/api/mock/source').json()['messages']['t1']
    assert sum(m['body']=='browser crash test' for m in data)==1

async def test_real_browser_send_verified_in_dom(server):
    from agent.browser import send_mock_approved
    before=(await asyncio.to_thread(server.get,'/api/mock/source')).json()['messages']['t6'][-1]['id']
    result=await send_mock_approved('t6','test reply without model','direct-browser-action',before)
    assert result['message_id']
    assert sum(m['id']==result['message_id'] for m in server.get('/api/mock/source').json()['messages']['t6'])==1
