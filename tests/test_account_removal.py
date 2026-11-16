"""Deleting an account also removes the customer's own bot (server, disk, token, conversations), never the owner's, and never silently."""
import httpx,pytest
from fastapi.testclient import TestClient

ADMIN={'Authorization':'Bearer '+'a'*32}
REG={'email':'ola@example.com','password':'bardzo-tajne-haslo','name':'Ola','mode':'drafts','adult':True,'terms':True}

@pytest.fixture
def c(tmp_path,monkeypatch):
    monkeypatch.setenv('CONTROL_DB_PATH',str(tmp_path/'c.db'));monkeypatch.setenv('ADMIN_TOKEN','a'*32)
    for k in ('PUBLIC_ORIGIN','OWNER_EMAIL','OWNER_SERVICE_ID','FLY_PUBLIC_DOMAIN','RENDER_API_KEY','RENDER_OWNER_ID','FLY_API_TOKEN'):monkeypatch.delenv(k,raising=False)
    import control.app as capp
    capp._HITS.clear();return capp

class Api:
    """A fake hosting API: records calls, can fail."""
    def __init__(self,status=200):self.calls=[];self.status=status
    def __call__(self,request):
        self.calls.append((request.method,request.url.path,dict(request.url.params)));return httpx.Response(self.status,json={})

def account(c,service_id,email='ola@example.com'):
    client=TestClient(c.app);client.post('/api/register',json={**REG,'email':email})
    c.q('UPDATE accounts SET render_service_id=?,status=? WHERE email=?',(service_id,'active',email))
    return client

def delete(client,password='bardzo-tajne-haslo'):return client.post('/api/account/delete',json={'password':password})
def pending(c):return c.q('SELECT * FROM instance_removals',fetch=True)

def test_fly_bot_is_removed_with_its_certificate(c,monkeypatch):
    from control import fly
    monkeypatch.setenv('FLY_API_TOKEN','FlyV1 fm2_x');monkeypatch.setenv('FLY_PUBLIC_DOMAIN','app.winq.site');monkeypatch.setenv('FLY_ROUTER_APP','winq-router')
    api=Api();monkeypatch.setattr(fly,'TRANSPORT',httpx.MockTransport(api))
    r=delete(account(c,'fly:winq-b-1a2b3c4d'));assert r.status_code==200
    assert ('DELETE','/v1/apps/winq-b-1a2b3c4d',{'force':'true'}) in [(m,p.replace('/v1/v1','/v1'),q) for m,p,q in api.calls] or any(p.endswith('/apps/winq-b-1a2b3c4d') and m=='DELETE' for m,p,q in api.calls)
    assert any(p.endswith('/apps/winq-router/certificates/1a2b3c4d.app.winq.site') and m=='DELETE' for m,p,q in api.calls)
    assert pending(c)==[] and c.q('SELECT 1 FROM accounts',fetch=True)==[]

def test_render_bot_is_removed(c,monkeypatch):
    from control import provision
    monkeypatch.setenv('RENDER_API_KEY','rnd_x');monkeypatch.setenv('RENDER_OWNER_ID','tea-x')
    api=Api(status=204);monkeypatch.setattr(provision,'TRANSPORT',httpx.MockTransport(api))
    assert delete(account(c,'srv-abc123')).status_code==200
    assert [(m,p) for m,p,q in api.calls]==[('DELETE','/v1/services/srv-abc123')] and pending(c)==[]

def test_a_failing_provider_keeps_the_bot_queued_and_the_retry_removes_it(c,monkeypatch):
    from control import fly
    monkeypatch.setenv('FLY_API_TOKEN','FlyV1 fm2_x')
    api=Api(status=500);monkeypatch.setattr(fly,'TRANSPORT',httpx.MockTransport(api))
    assert delete(account(c,'fly:winq-u7-abcdef')).status_code==200                      # the customer's deletion never fails because of the hosting API
    row=pending(c);assert len(row)==1 and row[0]['service_id']=='fly:winq-u7-abcdef' and row[0]['attempts']==1 and 'HTTP 500' in row[0]['last_error']
    admin=TestClient(c.app)
    assert admin.get('/admin/instances/removals',headers=ADMIN).json()['count']==1
    api.status=404                                                                       # gone already: counts as removed
    r=admin.post('/admin/instances/removals',headers=ADMIN).json();assert r['removed']==1 and r['left']==0 and pending(c)==[]

def test_without_hosting_credentials_it_waits_instead_of_pretending(c):
    assert delete(account(c,'fly:winq-u7-abcdef')).status_code==200
    row=pending(c);assert len(row)==1 and 'not configured' in row[0]['last_error']

def test_the_owners_own_bot_is_never_touched(c,monkeypatch):
    from control import provision
    monkeypatch.setenv('RENDER_API_KEY','rnd_x');monkeypatch.setenv('RENDER_OWNER_ID','tea-x');monkeypatch.setenv('OWNER_SERVICE_ID','srv-owner1')
    api=Api();monkeypatch.setattr(provision,'TRANSPORT',httpx.MockTransport(api))
    deletes=lambda:[x for x in api.calls if x[0]=='DELETE']                                # (registering the owner only reads the service)
    assert delete(account(c,'srv-owner1')).status_code==200 and deletes()==[] and pending(c)==[]
    monkeypatch.setenv('OWNER_EMAIL','boss@example.com')                                  # also by e-mail, whatever id is stored
    assert delete(account(c,'srv-other9','boss@example.com')).status_code==200 and deletes()==[] and pending(c)==[]

def test_account_without_a_bot_and_wrong_password(c):
    assert delete(account(c,None),'zle-haslo').status_code==401 and len(c.q('SELECT 1 FROM accounts',fetch=True))==1   # nothing happens
    assert delete(TestClient(c.app)).status_code==401
    cl=account(c,None,'jan@example.com');assert delete(cl).status_code==200 and pending(c)==[]

def test_odd_ids_are_refused_rather_than_sent_to_the_provider(c,monkeypatch):
    from control import provision,fly
    api=Api();monkeypatch.setattr(provision,'TRANSPORT',httpx.MockTransport(api));monkeypatch.setattr(fly,'TRANSPORT',httpx.MockTransport(api))
    with pytest.raises(RuntimeError):provision.delete_instance('../../services')
    with pytest.raises(fly.FlyError):provision.delete_instance('fly:../orgs')
    assert api.calls==[]

def test_account_deleted_while_its_bot_was_being_built_does_not_leave_the_bot(c,monkeypatch):
    from control import provision
    monkeypatch.setenv('RENDER_API_KEY','rnd_x');monkeypatch.setenv('RENDER_OWNER_ID','tea-x');monkeypatch.setenv('RENDER_ENV_GROUP_ID','evg-x')
    api=Api(status=204);monkeypatch.setattr(provision,'TRANSPORT',httpx.MockTransport(api))
    client=TestClient(c.app);client.post('/api/register',json=REG);aid=c.q('SELECT id FROM accounts',fetch=True)[0]['id']
    def build(account_id,plan=None):                                                     # the customer deletes the account while the server is being created
        c.q('DELETE FROM accounts WHERE id=?',(account_id,));return {'service_id':'srv-built1','url':'https://x.onrender.com','sso_secret':'s'*40}
    monkeypatch.setattr(provision,'create_instance',build)
    assert c.run_provision(aid)=='missing'
    assert ('DELETE','/v1/services/srv-built1',{}) in api.calls and pending(c)==[]
