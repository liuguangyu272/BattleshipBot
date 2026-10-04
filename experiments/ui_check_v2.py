"""Run the UI v2 regressions through real HTTP and headless Edge DOMs.

No remote debugging port is used. This script starts and stops its own game
server (8767) and injects assertions through a local test proxy (8768).
Original v1 results remain untouched; outputs go to results/revision-v2/ui-*.
"""
from __future__ import annotations

from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from battleship.core import save_json, verify_replay

UPSTREAM = "http://127.0.0.1:8767"
OUTPUT = ROOT / "results" / "revision-v2"
WORK = ROOT / "work" / "ui-check-v2"

SCRIPT = r"""
<script>
(async()=>{
  const checks=JSON.parse(sessionStorage.getItem('checks')||'[]');
  const wait=async predicate=>{
    for(let i=0;i<5000;i++){
      if(predicate())return;
      await new Promise(resolve=>setTimeout(resolve,10));
    }
    throw Error('DOM wait timed out');
  };
  const check=(condition,label)=>{
    if(!condition)throw Error(label);
    checks.push(label);
  };
  const captureDownload=async()=>{
    const create=URL.createObjectURL,click=HTMLAnchorElement.prototype.click;
    let captured=null,name=null;
    URL.createObjectURL=blob=>{captured=blob;return 'blob:ui-check-download'};
    HTMLAnchorElement.prototype.click=function(){name=this.download};
    try{
      document.getElementById('download').click();
      await wait(()=>captured!==null);
      return {data:JSON.parse(await captured.text()),name};
    }finally{
      URL.createObjectURL=create;
      HTMLAnchorElement.prototype.click=click;
    }
  };
  try{
    await wait(()=>!busy&&(state!==null||pendingFleet!==null));
    check(document.querySelectorAll('#own button').length===100,'100 own cells');
    check(document.querySelectorAll('#enemy button').length===100,'100 enemy cells');
    if(sessionStorage.getItem('phase')!=='after-refresh'){
      document.getElementById('opponent').value='balanced';
      document.getElementById('new').click();
      await wait(()=>state?.mode==='human'&&!busy);
      check(state.enemy_fleet===null,'hidden enemy withheld');
      document.querySelector('#enemy button:not(:disabled)').click();
      await wait(()=>state.observation.shots_taken===1&&!busy);
      check(state.observation.incoming.filter(x=>x!==0).length===1,'human action and AI response');
      check(state.opponent==='balanced','balanced opponent completes a human game turn');
      sessionStorage.setItem('expected',JSON.stringify(state.observation));
      sessionStorage.setItem('checks',JSON.stringify(checks));
      sessionStorage.setItem('phase','after-refresh');
      location.reload();
      return;
    }
    check(JSON.stringify(state.observation)===sessionStorage.getItem('expected'),
          'real page refresh restores the exact active game');
    check(state.enemy_fleet===null,'refresh does not reveal enemy fleet');
    check(document.getElementById('opponent').value==='balanced','refresh restores the selected opponent');
    document.querySelector('#enemy button:not(:disabled)').click();
    await wait(()=>state.observation.shots_taken===2&&!busy);
    check(state.observation.incoming.filter(x=>x!==0).length===2,'restored game can continue');
    const card=document.querySelectorAll('details')[1];
    card.querySelector('summary').click();
    check(card.open,'explanation card stays open');
    document.getElementById('opponent').value='random';
    document.getElementById('demo').click();
    await wait(()=>state?.mode==='demo'&&!busy);
    while(state.observation.winner===null){
      document.getElementById('next').click();
      await wait(()=>!busy);
    }
    check(state.enemy_fleet!==null,'complete demonstration reveals enemy fleet');
    check(!document.getElementById('download').disabled,'completed game download enabled');
    check(card.open,'explanation card preserved through game updates');
    const serverReplay=await(await fetch('/api/replay')).json();
    const serverDownload=await captureDownload();
    check(JSON.stringify(serverDownload.data)===JSON.stringify(serverReplay),
          'normal game download matches server replay');
    const fixture=await(await fetch('/qa/fixture')).json();
    check(JSON.stringify(fixture.fleets)!==JSON.stringify(serverReplay.fleets),
          'imported replay is a different game');
    const transfer=new DataTransfer();
    transfer.items.add(new File([JSON.stringify(fixture)],'different-replay.json',{type:'application/json'}));
    document.getElementById('file').files=transfer.files;
    document.getElementById('file').dispatchEvent(new Event('change'));
    await wait(()=>replay!==null);
    check(document.getElementById('log').textContent==='尚未开火。','replay frame zero clears previous battle log');
    check(document.getElementById('timing').textContent==='','replay clears unrelated AI timing');
    const frame=Math.min(23,fixture.events.length);
    document.getElementById('scrub').value=frame;
    document.getElementById('scrub').dispatchEvent(new Event('input'));
    const visible=fixture.events.slice(0,frame).slice(-12);
    const actual=[...document.querySelectorAll('#log div')].map(line=>line.textContent);
    check(actual.length===visible.length&&visible.every((event,i)=>
      actual[i].startsWith(String(event.ply+1).padStart(3,'0'))&&actual[i].includes(coord(event.cell))),
      'scrubbed battle log matches the selected replay frame');
    const received=fixture.events.slice(0,frame).filter(event=>event.player===1).length;
    check(document.getElementById('ownstat').textContent.includes('受到 '+received+' 发'),
          'replay shot statistics follow the selected frame');
    check(document.getElementById('shuffle').disabled,'shuffle cannot alter the hidden live game during replay');
    const importedDownload=await captureDownload();
    check(JSON.stringify(importedDownload.data)===JSON.stringify(fixture)&&
          importedDownload.name==='different-replay.json','download saves the displayed imported replay');
    document.getElementById('scrub').value=0;
    document.getElementById('scrub').dispatchEvent(new Event('input'));
    check(document.getElementById('log').textContent==='尚未开火。','scrubbing backward removes future battle log entries');
    document.getElementById('exitReplay').click();
    check(replay===null&&document.getElementById('log').textContent.includes(coord(state.events.at(-1).cell)),
          'exit replay restores the original live game battle log');
    check(document.getElementById('timing').textContent.startsWith('AI '),'exit replay restores live game timing');
    const restoredDownload=await captureDownload();
    check(JSON.stringify(restoredDownload.data)===JSON.stringify(serverReplay),
          'exit replay restores the original game download');
    check(document.documentElement.scrollWidth<=window.innerWidth,'no horizontal overflow');
    document.body.dataset.qa='passed';
    sessionStorage.clear();
    await fetch('/qa/result',{method:'POST',body:JSON.stringify({
      ok:true,checks,plies:serverReplay.events.length,winner:serverReplay.winner,width:innerWidth
    })});
  }catch(error){
    document.body.dataset.qa='failed';
    await fetch('/qa/result',{method:'POST',body:JSON.stringify({ok:false,checks,error:String(error)})});
  }
})();
</script>
"""


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    WORK.mkdir(parents=True, exist_ok=True)
    results = {"ports": {"game": 8767, "proxy": 8768}, "browser": []}
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    server = thread = game = None
    with (OUTPUT / "ui-server.log").open("w", encoding="utf-8") as game_log:
        try:
            game = subprocess.Popen(
                [sys.executable, "-m", "battleship", "serve", "--port", "8767", "--no-browser"],
                cwd=ROOT, stdout=game_log, stderr=subprocess.STDOUT, creationflags=creationflags,
            )
            results["game_pid"] = game.pid
            for _ in range(200):
                if game.poll() is not None:
                    raise RuntimeError("test game server exited; inspect ui-server.log")
                try:
                    html = urllib.request.urlopen(UPSTREAM, timeout=1).read().decode()
                    break
                except (urllib.error.URLError, TimeoutError):
                    time.sleep(0.05)
            else:
                raise RuntimeError("test game server did not become ready")
            token = re.search(r"const token='([^']+)'", html).group(1)

            def request(path, body):
                return json.load(urllib.request.urlopen(urllib.request.Request(
                    UPSTREAM + "/api/" + path, json.dumps(body).encode(),
                    {"Content-Type": "application/json", "X-Game-Token": token},
                ), timeout=10))

            state = request("new", {"mode": "demo", "seed": 4202, "opponent": "random"})
            while state["observation"]["winner"] is None:
                assert state["enemy_fleet"] is None
                state = request("step", {})
            replay = json.load(urllib.request.urlopen(UPSTREAM + "/api/replay"))
            verify_replay(replay)
            results["http"] = {"plies": len(replay["events"]), "winner": replay["winner"], "replay_verified": True}
            fixture = (ROOT / "replays" / "demo.json").read_bytes()
            done = threading.Event()

            class Proxy(BaseHTTPRequestHandler):
                def send(self, raw, status=200, mime="application/json"):
                    self.send_response(status)
                    self.send_header("Content-Type", mime)
                    self.send_header("Content-Length", str(len(raw)))
                    self.send_header("Cache-Control", "no-store")
                    self.end_headers()
                    self.wfile.write(raw)

                def do_GET(self):
                    if self.path == "/qa/fixture":
                        self.send(fixture)
                        return
                    try:
                        response = urllib.request.urlopen(UPSTREAM + self.path, timeout=10)
                    except urllib.error.HTTPError as error:
                        response = error
                    raw = response.read()
                    if self.path == "/":
                        raw = raw.replace(b"</body>", SCRIPT.encode() + b"</body>")
                    self.send(raw, response.status, response.headers.get("Content-Type"))

                def do_POST(self):
                    data = self.rfile.read(int(self.headers.get("Content-Length", "0")))
                    if self.path == "/qa/result":
                        results["browser"].append(json.loads(data))
                        save_json(OUTPUT / "ui-check.json", results)
                        self.send(b"{}")
                        done.set()
                        return
                    req = urllib.request.Request(UPSTREAM + self.path, data, {
                        "Content-Type": "application/json", "X-Game-Token": token,
                    })
                    try:
                        response = urllib.request.urlopen(req, timeout=10)
                    except urllib.error.HTTPError as error:
                        response = error
                    self.send(response.read(), response.status)

                def log_message(self, *args):
                    pass

            server = HTTPServer(("127.0.0.1", 8768), Proxy)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            edge = Path("C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe")
            if not edge.exists():
                raise RuntimeError("Edge not found at the Windows default location")
            for width, height, name in [(1365, 1250, "desktop"), (540, 1700, "mobile")]:
                done.clear()
                with (OUTPUT / f"ui-{name}-browser.log").open("w", encoding="utf-8") as browser_log:
                    subprocess.run([
                        str(edge), "--headless", "--disable-gpu", "--no-first-run",
                        "--virtual-time-budget=60000", f"--window-size={width},{height}",
                        f"--user-data-dir={WORK / (name + '-' + str(time.time_ns()))}",
                        f"--screenshot={OUTPUT / ('ui-' + name + '-verified.png')}",
                        "http://127.0.0.1:8768",
                    ], timeout=90, check=True, stdout=browser_log, stderr=subprocess.STDOUT,
                       creationflags=creationflags)
                if not done.wait(10):
                    raise RuntimeError(f"{name} browser did not report test completion")
                print(json.dumps(results["browser"][-1], ensure_ascii=False), flush=True)
                assert results["browser"][-1]["ok"]
        finally:
            if server:
                server.shutdown()
                server.server_close()
            if thread:
                thread.join(timeout=5)
            if game and game.poll() is None:
                game.terminate()
                try:
                    game.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    game.kill()
                    game.wait(timeout=5)
            results["game_stopped"] = game is None or game.poll() is not None
            results["proxy_stopped"] = thread is None or not thread.is_alive()
            save_json(OUTPUT / "ui-check.json", results)


if __name__ == "__main__":
    main()
