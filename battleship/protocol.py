"""JSONL v1 stdin/stdout adapter and a hard-deadline subprocess opponent."""
from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import queue
import subprocess
import sys
import threading

from .core import Rules, validate_fleet


def validate_observation(obs, rules):
    if Rules.from_dict(obs["rules"]) != rules:
        raise ValueError("observation rules changed")
    grid = obs["grid"]
    if len(grid) != rules.size ** 2 or any(type(v) is not int or v not in (0, 1, 2, 3) for v in grid):
        raise ValueError("invalid observation grid")
    if obs["legal_actions"] != [i for i, v in enumerate(grid) if v == 0]:
        raise ValueError("legal_actions inconsistent with grid")
    remaining = list(rules.fleet)
    sunk_cells = set()
    for ship in obs["sunk"]:
        validate_fleet([ship], Rules(rules.size, (len(ship),)))
        if any(c in sunk_cells or grid[c] != 3 for c in ship):
            raise ValueError("invalid sunk cells")
        sunk_cells.update(ship)
        remaining.remove(len(ship))
    if sunk_cells != {i for i, v in enumerate(grid) if v == 3}:
        raise ValueError("sunk metadata inconsistent")
    if Counter(remaining) != Counter(obs["remaining"]):
        raise ValueError("remaining fleet inconsistent")
    if type(obs["done"]) is not bool or obs["done"] != (not remaining):
        raise ValueError("done flag inconsistent")
    if obs["shots_taken"] != sum(v != 0 for v in grid):
        raise ValueError("shots_taken inconsistent")


def run_protocol(name):
    from .bots import make_bot
    bot, rules = None, None
    for line in sys.stdin:
        try:
            if len(line) > 1000000:
                raise ValueError("request too large")
            msg = json.loads(line)
            if msg.get("v", 1) != 1:
                raise ValueError("unsupported protocol version")
            op = msg["op"]
            if op == "reset":
                bot = make_bot(name)
                rules = Rules.from_dict(msg["rules"])
                bot.reset(rules.to_dict(), int(msg["seed"]))
                response = {"ok": True, "v": 1}
            elif bot is None:
                raise ValueError("reset required")
            elif op == "place":
                response = {"fleet": bot.place()}
            elif op == "act":
                validate_observation(msg["observation"], rules)
                response = {"action": bot.act(msg["observation"])}
            else:
                raise ValueError("unknown operation")
        except Exception as error:
            response = {"error": type(error).__name__, "message": str(error)}
        print(json.dumps(response, separators=(",", ":")), flush=True)


class SubprocessBot:
    """Trusted local executable; process boundary is NOT an OS security sandbox.

    Spec: {argv:[...], cwd:optional, timeout_ms:1000}. No shell interpretation.
    stdout must contain one JSON object per request. stderr inherits parent.
    """
    def __init__(self, spec):
        if isinstance(spec, (str, Path)):
            spec = json.loads(Path(spec).read_text(encoding="utf-8"))
        argv = spec["argv"]
        if not isinstance(argv, list) or not argv or not all(isinstance(s, str) for s in argv):
            raise ValueError("argv must be a nonempty string list")
        self.timeout = float(spec.get("timeout_ms", 1000)) / 1000
        self.setup_timeout = float(spec.get("setup_timeout_ms", 5000)) / 1000
        if not 0 < self.timeout <= 60:
            raise ValueError("timeout_ms must be 0..60000")
        if not 0 < self.setup_timeout <= 60:
            raise ValueError("setup_timeout_ms must be 0..60000")
        self.process = subprocess.Popen(argv, cwd=spec.get("cwd"), stdin=subprocess.PIPE,
                                        stdout=subprocess.PIPE, text=True, encoding="utf-8",
                                        bufsize=1, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.queue = queue.Queue()
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()

    def _read(self):
        try:
            while True:
                line = self.process.stdout.readline(1000001)
                if not line:
                    break
                self.queue.put(line)
                if len(line) > 1000000:
                    break
        finally:
            self.queue.put(None)

    def _call(self, data, timeout=None):
        try:
            self.process.stdin.write(json.dumps({"v": 1, **data}) + "\n")
            self.process.stdin.flush()
            line = self.queue.get(timeout=self.timeout if timeout is None else timeout)
        except queue.Empty:
            self.close()
            raise TimeoutError("external bot deadline exceeded") from None
        if line is None:
            raise RuntimeError("external bot exited")
        if len(line) > 1000000:
            raise ValueError("external response too large")
        result = json.loads(line)
        if not isinstance(result, dict) or "error" in result:
            raise ValueError("external bot rejected request: " + str(result))
        return result

    def reset(self, rules, seed):
        result = self._call({"op": "reset", "rules": rules, "seed": str(seed)}, self.setup_timeout)
        if result.get("ok") is not True:
            raise ValueError("external reset did not acknowledge ok=true")

    def place(self):
        return self._call({"op": "place"}, self.setup_timeout)["fleet"]

    def act(self, observation):
        return self._call({"op": "act", "observation": observation})["action"]

    def close(self):
        if self.process.poll() is None:
            self.process.terminate()
        try:
            self.process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=2)
        if self.process.stdin:
            self.process.stdin.close()
        self.reader.join(timeout=2)
        if self.process.stdout:
            self.process.stdout.close()
