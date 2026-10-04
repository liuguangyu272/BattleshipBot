from __future__ import annotations

from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from pathlib import Path
import random
import secrets
import time
import webbrowser

from .bots import make_bot
from .core import Game, Rules, deploy, save_json

ROOT = Path(__file__).resolve().parent.parent


class Session:
    def __init__(self, mode="human", seed=None, fleet=None, opponent="champion"):
        if mode not in ("human", "demo") or opponent not in ("champion", "admiral", "density", "hunt", "random"):
            raise ValueError("invalid mode or bot")
        seed = secrets.randbits(32) if seed is None else int(seed)
        self.mode = mode
        self.bots = [make_bot("champion"), make_bot(opponent)]
        rules = Rules()
        for i, bot in enumerate(self.bots):
            bot.reset(rules.to_dict(), seed * 3 + i)
        fleets = [b.place() for b in self.bots]
        if fleet is not None:
            fleets[0] = fleet
        self.game = Game(fleets, rules)
        self.saved = None
        self.last_ms = 0

    def view(self):
        obs = self.game.observe(0)
        return {"observation": obs, "mode": self.mode, "events": self.game.events[-12:],
                "last_ms": self.last_ms, "replay": self.saved,
                "enemy_fleet": [list(s) for s in self.game.boards[1].fleet] if self.game.winner is not None else None}

    def step(self, cell=None):
        game = self.game
        if game.winner is not None:
            raise ValueError("game is over")
        if self.mode == "human":
            if game.turn != 0:
                raise ValueError("not human's turn")
            game.step(0, cell)
            if game.winner is None:
                start = time.perf_counter()
                game.step(1, self.bots[1].act(game.observe(1)))
                self.last_ms = (time.perf_counter()-start)*1000
        else:
            p = game.turn
            start = time.perf_counter()
            game.step(p, self.bots[p].act(game.observe(p)))
            self.last_ms = (time.perf_counter()-start)*1000
        if game.winner is not None and self.saved is None:
            filename = f"ui-{time.time_ns()}.json"
            save_json(ROOT / "replays" / filename, game.replay())
            self.saved = filename
        return self.view()


def serve(port=8765, open_browser=True):
    session = None
    token = secrets.token_urlsafe(24)

    class Handler(BaseHTTPRequestHandler):
        def send(self, data, status=200, mime="application/json; charset=utf-8"):
            body = data.encode("utf-8") if isinstance(data, str) else json.dumps(data, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path == "/":
                html = (ROOT / "web" / "index.html").read_text(encoding="utf-8").replace("__TOKEN__", token)
                self.send(html, mime="text/html; charset=utf-8")
            elif self.path == "/api/state":
                self.send(session.view() if session else {"ready": True})
            elif self.path == "/api/replay" and session and session.game.winner is not None:
                self.send(session.game.replay())
            else:
                self.send({"error": "not found"}, 404)

        def do_POST(self):
            nonlocal session
            if self.headers.get("X-Game-Token") != token:
                self.send({"error": "invalid local session token"}, 403)
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 <= length <= 100000:
                    raise ValueError("request too large")
                body = json.loads(self.rfile.read(length) or b"{}")
                if self.path == "/api/new":
                    session = Session(body.get("mode", "human"), body.get("seed"), body.get("fleet"), body.get("opponent", "champion"))
                    self.send(session.view())
                elif self.path == "/api/step" and session:
                    self.send(session.step(body.get("cell")))
                elif self.path == "/api/shuffle":
                    self.send({"fleet": deploy(random.Random(secrets.randbits(64)))})
                else:
                    self.send({"error": "start a game first"}, 400)
            except (ValueError, TypeError, KeyError) as error:
                self.send({"error": str(error)}, 400)

        def log_message(self, fmt, *args):
            pass

    server = HTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{server.server_port}"
    print("Battleship:", url, "(Ctrl+C to stop)", flush=True)
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
