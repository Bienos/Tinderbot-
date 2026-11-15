"""ASGI boundary: strict configured host, bounded bodies, security headers on all responses."""
from urllib.parse import urlsplit
import asyncio,time
import os
from starlette.responses import JSONResponse
MAX_BODY_BYTES=65536

def internal_request(scope):
    from agent.auth import same_secret,token
    headers={k.lower():v for k,v in scope['headers']}
    auth=headers.get(b'authorization',b'').decode('latin1')
    peer=(scope.get('client') or ('',0))[0]
    return peer in ('127.0.0.1','::1') and headers.get(b'host',b'').lower()==b'127.0.0.1:8765' and auth.startswith('Bearer ') and same_secret(auth[7:],token())

class BodyTooLarge(Exception):pass

class SecurityBoundary:
    def __init__(self,app):self.app=app
    async def __call__(self,scope,receive,send):
        if scope['type']!='http':return await self.app(scope,receive,send)
        headers={k.lower():v for k,v in scope['headers']}
        origin=os.getenv('PUBLIC_ORIGIN','http://127.0.0.1:8765')
        expected=urlsplit(origin).netloc.lower().encode('ascii')
        async def safe_send(message):
            if message['type']=='http.response.start':
                existing={k.lower():v for k,v in message.get('headers',[])}
                existing.update({b'cache-control':b'no-store',b'x-content-type-options':b'nosniff',
                    b'referrer-policy':b'no-referrer',b'x-frame-options':b'DENY',
                    b'content-security-policy':b"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'; object-src 'none'"})
                if origin.startswith('https://'):existing[b'strict-transport-security']=b'max-age=31536000'
                message={**message,'headers':list(existing.items())}
            await send(message)
        async def reject(status,detail):await JSONResponse({'detail':detail},status)(scope,receive,safe_send)
        local_health=scope['path']=='/health' and (scope.get('client') or ('',0))[0] in ('127.0.0.1','::1') and headers.get(b'host',b'').lower()==b'127.0.0.1:8765'
        if headers.get(b'host',b'').lower()!=expected and not local_health and not internal_request(scope):return await reject(400,'Untrusted Host header')
        try:
            size=int(headers.get(b'content-length',b'0'))
            if size<0:raise ValueError()
        except ValueError:return await reject(400,'Invalid Content-Length')
        if size>MAX_BODY_BYTES:return await reject(413,'Request body too large')
        # Cap while reading, including chunked bodies, before JSON parsing or middleware buffering.
        body=bytearray();deadline=time.monotonic()+10
        while True:
            try:message=await asyncio.wait_for(receive(),max(.001,deadline-time.monotonic()))
            except TimeoutError:return await reject(408,'Request body timed out')
            if message['type']=='http.disconnect':return
            body.extend(message.get('body',b''))
            if len(body)>MAX_BODY_BYTES:return await reject(413,'Request body too large')
            if not message.get('more_body',False):break
        delivered=False
        async def bounded_receive():
            nonlocal delivered
            if delivered:return await receive()
            delivered=True
            return {'type':'http.request','body':bytes(body),'more_body':False}
        await self.app(scope,bounded_receive,safe_send)
