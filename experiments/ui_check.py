"""Real HTTP + browser DOM smoke test, without remote debugging ports.

Run the local game server on 8765 first. An ephemeral loopback test proxy injects
DOM tests into a copy of the served HTML. It never changes the deliverable UI.
"""
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
import json
import re
import subprocess
import threading
import urllib.request
import urllib.error
import time

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM = 'http://127.0.0.1:8765'


SCRIPT = r"""
<script>
(async()=>{
const checks=[];
const wait=async fn=>{for(let i=0;i<3000;i++){if(fn())return;await new Promise(r=>setTimeout(r,10))}throw Error('DOM wait timed out')};
const check=(condition,label)=>{if(!condition)throw Error(label);checks.push(label)};
try{
await wait(()=>pendingFleet!==null);
check(document.querySelectorAll('#own button').length===100,'100 own cells');
check(document.querySelectorAll('#enemy button').length===100,'100 enemy cells');
document.getElementById('new').click();await wait(()=>state?.mode==='human'&&!busy);
check(state.enemy_fleet===null,'hidden enemy withheld');
document.querySelector('#enemy button:not(:disabled)').click();await wait(()=>state.observation.shots_taken===1&&!busy);
check(state.observation.incoming.filter(x=>x!==0).length===1,'human action and AI response');
const card=document.querySelectorAll('details')[1];card.querySelector('summary').click();check(card.open,'rule card stays open');
document.getElementById('demo').click();await wait(()=>state?.mode==='demo'&&!busy);
while(state.observation.winner===null){document.getElementById('next').click();await wait(()=>!busy)}
check(state.enemy_fleet!==null,'postgame reveal');
check(!document.getElementById('download').disabled,'replay download enabled');
check(card.open,'card preserved through game updates');
const r=await(await fetch('/api/replay')).json();
check(r.events.length>0&&r.winner!==null,'complete replay available');
replay=r;document.getElementById('scrub').max=r.events.length;document.getElementById('scrub').value=Math.floor(r.events.length/2);drawReplay();
check(document.getElementById('status').textContent.includes('赛后回放'),'replay scrubber renders');
replay=null;render();
check(document.documentElement.scrollWidth<=window.innerWidth,'no horizontal overflow');
document.body.dataset.qa='passed';
await fetch('/qa/result',{method:'POST',body:JSON.stringify({ok:true,checks,plies:r.events.length,winner:r.winner,width:innerWidth})});
}catch(e){document.body.dataset.qa='failed';await fetch('/qa/result',{method:'POST',body:JSON.stringify({ok:false,checks,error:String(e)})})}
})();
</script>
"""


def main():
    html=urllib.request.urlopen(UPSTREAM).read().decode()
    token=re.search(r"const token='([^']+)'",html).group(1)
    def request(path,body):
        return json.load(urllib.request.urlopen(urllib.request.Request(UPSTREAM+'/api/'+path,
            json.dumps(body).encode(),{'Content-Type':'application/json','X-Game-Token':token})))
    state=request('new',{'mode':'demo','seed':4201})
    n=0
    while state['observation']['winner'] is None:
        assert state['enemy_fleet'] is None
        state=request('step',{})
        n+=1
    replay=json.load(urllib.request.urlopen(UPSTREAM+'/api/replay'))
    from battleship.core import verify_replay, save_json
    verify_replay(replay)
    results={'http':{'plies':n,'winner':state['observation']['winner'],'replay_verified':True},'browser':[]}
    done=threading.Event()
    class Proxy(BaseHTTPRequestHandler):
        def do_GET(self):
            try:
                response=urllib.request.urlopen(UPSTREAM+self.path)
            except urllib.error.HTTPError as e:
                response=e
            raw=response.read()
            if self.path=='/':
                raw=raw.replace(b'</body>',SCRIPT.encode()+b'</body>')
            self.send_response(response.status)
            self.send_header('Content-Type',response.headers.get('Content-Type'))
            self.send_header('Content-Length',str(len(raw)))
            self.end_headers();self.wfile.write(raw)
        def do_POST(self):
            data=self.rfile.read(int(self.headers.get('Content-Length','0')))
            if self.path=='/qa/result':
                result=json.loads(data)
                results['browser'].append(result)
                save_json(ROOT/'results/ui-check.json',results)
                self.send_response(200);self.end_headers();self.wfile.write(b'{}');done.set()
                return
            req=urllib.request.Request(UPSTREAM+self.path,data,{'Content-Type':'application/json','X-Game-Token':token})
            try:
                response=urllib.request.urlopen(req)
            except urllib.error.HTTPError as e:
                response=e
            raw=response.read()
            self.send_response(response.status)
            self.send_header('Content-Type','application/json')
            self.send_header('Content-Length',str(len(raw)))
            self.end_headers();self.wfile.write(raw)
        def log_message(self,*args):
            pass
    server=HTTPServer(('127.0.0.1',8766),Proxy)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    edge=Path('C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe')
    try:
        for width,height,name in [(1365,1250,'desktop'),(430,1500,'mobile')]:
            done.clear()
            subprocess.run([str(edge),'--headless','--disable-gpu','--no-first-run',
                            '--virtual-time-budget=30000',f'--window-size={width},{height}',
                            f'--screenshot={ROOT / "results" / ("ui-"+name+"-verified.png")}',
                            'http://127.0.0.1:8766'],timeout=60,check=True)
            if not done.wait(30):
                raise RuntimeError('browser did not report test completion')
            print(json.dumps(results['browser'][-1],ensure_ascii=False),flush=True)
            assert results['browser'][-1]['ok']
    finally:
        server.shutdown();server.server_close();thread.join()
        save_json(ROOT/'results/ui-check.json',results)


if __name__=='__main__':
    import sys
    sys.path.insert(0,str(ROOT))
    main()
