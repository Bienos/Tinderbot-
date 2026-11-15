"""Measure mock HTTP counts; never contact Tinder. Optional baseline is an explicit local source tree."""
import argparse,json,os,subprocess,sys,tempfile
from pathlib import Path
RUNNER=r'''
import asyncio,json,os,sys,tempfile
from pathlib import Path
import httpx
sys.path.insert(0,str(Path.cwd()/'tests'))
from test_tinder import Source,TOKEN,OWNER,CID,TID
from agent import tinder,storage as s,runtime as rt,service
from agent.engine import Decision
async def run():
 with tempfile.TemporaryDirectory() as temp:
  s.DB_PATH=Path(temp)/'bench.db';rt.init()
  fake=Source();tinder.client=lambda:tinder.TinderClient(TOKEN,transport=httpx.MockTransport(fake.handle))
  await tinder.connect();await tinder.sync_connection(CID)
  first=len(fake.requests)
  for _ in range(5):await tinder.sync_connection(CID)
  repeated=len(fake.requests)-first
  with s.connect() as db:db.execute('INSERT INTO grants VALUES(?,?,?,?)',(TID,1,1,1))
  await tinder.sync_connection(CID)
  service.generate=lambda *a:(Decision(action='reply',reply='hello demo',note='offline benchmark',claims=[]),'LLM-reviewed:offline-benchmark')
  before=len(fake.requests)
  while (job:=rt.claim()):await service.process_job(job)
  print('BENCHMARK:'+json.dumps({'threads':2,'unchanged_polls':5,'warmup_requests':first,'unchanged_poll_requests':repeated,'send_workflow_requests':len(fake.requests)-before,'message_posts':len(fake.posts),'verified_sends':len(s.rows("SELECT * FROM actions WHERE status='sent'"))}))
asyncio.run(run())
'''
def measure(path):
    env={**os.environ,'TINDER_ENABLED':'true','TINDER_AUTH_TOKEN':'fake-private-token-for-offline-tests',
         'SEED_SIMULATOR':'false','WORKER_ENABLED':'false','DATING_AGENT_SOURCE':'fixture',
         'TINDER_REQUESTS_PER_MINUTE':'1000','TINDER_REQUESTS_PER_HOUR':'10000'}
    env.pop('OPENAI_API_KEY',None);env.pop('TINDER_OWNER_ID',None)
    result=subprocess.run([sys.executable,'-c',RUNNER],cwd=path,env=env,capture_output=True,text=True,timeout=60)
    if result.returncode:raise RuntimeError(result.stderr)
    return json.loads(next(l[len('BENCHMARK:'):] for l in result.stdout.splitlines() if l.startswith('BENCHMARK:')))
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--baseline',type=Path);args=p.parse_args()
    root=Path(__file__).resolve().parents[1];report={'method':'httpx.MockTransport with two fictional matches, not a live ban/detection test','current':measure(root)}
    if args.baseline:
        report['baseline']=measure(args.baseline.resolve())
        report['unchanged_poll_request_reduction_percent']=100*(1-report['current']['unchanged_poll_requests']/report['baseline']['unchanged_poll_requests'])
        report['send_workflow_request_reduction_percent']=100*(1-report['current']['send_workflow_requests']/report['baseline']['send_workflow_requests'])
    (root/'reports/account_traffic_benchmark.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))
