"""Real Playwright interactions, deliberately restricted to our fictional loopback site."""
import os,json,asyncio,contextlib
from urllib.parse import urlparse
from contextlib import asynccontextmanager
from playwright.async_api import async_playwright
MOCK_ORIGIN='http://127.0.0.1:8765'

def assert_allowed(url):
    p=urlparse(url)
    if p.scheme!='http' or p.netloc!='127.0.0.1:8765' or p.username or p.password:
        raise PermissionError('This adapter only supports the fictional loopback site')

@asynccontextmanager
async def page_context():
    from agent.auth import token
    async with async_playwright() as p:
        kwargs={'headless':True}
        if os.getenv('CHROMIUM_EXECUTABLE'):kwargs['executable_path']=os.environ['CHROMIUM_EXECUTABLE']
        # Isolated ephemeral context. No third-party sessions or stealth flags.
        browser=await p.chromium.launch(**kwargs)
        ctx=await browser.new_context(extra_http_headers={'Authorization':'Bearer '+token()})
        async def restrict(route):
            try:assert_allowed(route.request.url)
            except PermissionError:await route.abort();return
            await route.continue_()
        await ctx.route('**/*',restrict)
        try:
            page=await ctx.new_page();page.set_default_timeout(7000)
            await page.goto(MOCK_ORIGIN+'/mock',wait_until='domcontentloaded')
            await page.locator('[data-source-ready]').wait_for()
            yield page
        finally:
            with contextlib.suppress(Exception):await asyncio.wait_for(ctx.close(),5)
            with contextlib.suppress(Exception):await asyncio.wait_for(browser.close(),5)

async def read_mock_threads():
    async with page_context() as page:
        while await page.locator('[data-load-more]:visible').count():
            count=await page.locator('[data-thread-button]').count()
            await page.locator('[data-load-more]').click()
            await page.wait_for_function('(n)=>document.querySelectorAll("[data-thread-button]").length>n',arg=count)
        ids=await page.locator('[data-thread-button]').evaluate_all('(els)=>els.map(e=>e.dataset.threadButton)')
        result={}
        for tid in ids:
            await page.locator('[data-thread-button]').filter(has_text='').evaluate_all('(els,id)=>els.find(e=>e.dataset.threadButton===id).click()',tid)
            await page.wait_for_function('(id)=>document.querySelector("#messages").dataset.threadId===id',arg=tid)
            result[tid]=await page.locator('[data-message-id]').evaluate_all('''els=>els.map(e=>({id:e.dataset.messageId,thread_id:e.parentElement.dataset.threadId,sender:e.dataset.sender,created_at:e.dataset.createdAt,body:e.textContent}))''')
        return result

async def send_mock_approved(thread_id,text,action_id=None,anchor=None):
    from uuid import uuid4
    async with page_context() as page:
        while await page.locator('[data-load-more]:visible').count():
            count=await page.locator('[data-thread-button]').count()
            await page.locator('[data-load-more]').click()
            await page.wait_for_function('(n)=>document.querySelectorAll("[data-thread-button]").length>n',arg=count)
        await page.locator('[data-thread-button]').evaluate_all('(els,id)=>els.find(e=>e.dataset.threadButton===id).click()',thread_id)
        await page.wait_for_function('(id)=>document.querySelector("#messages").dataset.threadId===id',arg=thread_id)
        actual=await page.locator('[data-message-id]').evaluate_all('els=>els.length?els[els.length-1].dataset.messageId:""')
        if anchor is not None and actual!=anchor:
            from agent.adapters import StaleAction
            raise StaleAction('Browser found a newer message')
        await page.locator('[data-chat-input]').fill(text)
        action_id=action_id or uuid4().hex
        await page.locator('[data-chat-input]').evaluate('(e,a)=>{e.dataset.action=a.id;e.dataset.anchor=a.anchor}',{'id':action_id,'anchor':anchor if anchor is not None else actual})
        async with page.expect_response(lambda r:'/api/mock/send' in r.url and r.request.method=='POST') as wait:
            await page.locator('[data-send-button]').click()
        response=await wait.value
        if response.status==409:
            from agent.adapters import StaleAction
            raise StaleAction('Atomic source freshness check rejected send')
        if not response.ok:raise RuntimeError('Simulator rejected send')
        # Confirm the stable action receipt in the visible DOM, independent of response-body capture.
        await page.wait_for_function('(id)=>Array.from(document.querySelectorAll("[data-message-id]")).some(e=>e.dataset.actionId===id)',arg=action_id,timeout=7000)
        receipt=await page.locator('[data-message-id]').evaluate_all('(els,id)=>{let e=els.find(e=>e.dataset.actionId===id);return {id:e.dataset.messageId,body:e.textContent}}',action_id)
        if receipt['body']!=text:raise RuntimeError('Observed message body differs from intended action')
        return {'ok':True,'message_id':receipt['id']}
