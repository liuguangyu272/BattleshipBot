from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
from contextlib import ExitStack
from dataclasses import asdict
import json
import hashlib
import os
import math
import platform
import random
import statistics
import time
from pathlib import Path

from .core import Rules, Game, Target, deploy, seed_for, save_json, validate_fleet
from .bots import make_bot, Policy


def play(bot_names=("admiral", "density"), seed=0, first=0, style="uniform",
         rules=Rules(), time_limit_ms=1000, policies=None):
    with ExitStack() as cleanup:
        bots = []
        for i, name in enumerate(bot_names):
            bot = make_bot(name, (policies or [None, None])[i])
            bots.append(bot)
            if hasattr(bot, "close"):
                cleanup.callback(bot.close)
        return _play(bots, bot_names, seed, first, style, rules, time_limit_ms)


def _play(bots, bot_names, seed, first, style, rules, time_limit_ms):
    faults, setup_ms = [], []
    fleets = [deploy(random.Random(seed_for(seed, "board", i)), rules,
                     "uniform" if style == "native" else style) for i in range(2)]
    for i, bot in enumerate(bots):
        start = time.perf_counter()
        try:
            # Independent private stream, NEVER a referee board seed.
            bot.reset(rules.to_dict(), seed_for(seed, "agent", i))
            if style == "native":
                fleets[i] = validate_fleet(bot.place(), rules)
            ms = (time.perf_counter()-start)*1000
            setup_ms.append(ms)
            if ms > 5000:
                raise TimeoutError("initialization exceeds 5000 ms")
        except Exception as error:
            faults.append({"player": i, "phase": "initialization", "type": type(error).__name__, "message": str(error)})
            break
    game = Game(fleets, rules, first)
    latency = [[], []]
    shots = [0, 0]
    while game.winner is None and not faults:
        p = game.turn
        start = time.perf_counter()
        try:
            action = bots[p].act(game.observe(p))
            ms = (time.perf_counter() - start) * 1000
            latency[p].append(ms)
            if ms > time_limit_ms:
                raise TimeoutError(f"{ms:.3f} ms exceeds {time_limit_ms} ms")
            game.step(p, action)
            shots[p] += 1
        except Exception as error:
            faults.append({"player": p, "phase": "action", "type": type(error).__name__, "message": str(error)})
            break
    winner = game.winner if not faults else 1 - faults[-1]["player"]
    record = {"seed": seed, "first": first, "bots": list(bot_names), "style": style,
              "winner": winner, "shots": shots, "faults": faults,
              "latency_ms": latency, "setup_ms": setup_ms, "plies": len(game.events)}
    replay = game.replay()
    replay["match"] = {k: v for k, v in record.items() if k != "latency_ms"}
    return record, replay


def wilson(wins, n):
    if not n:
        return [0, 1]
    z = 1.959963984540054
    p = wins/n
    mid = (p+z*z/(2*n))/(1+z*z/n)
    half = z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/(1+z*z/n)
    return [max(0, mid-half), min(1, mid+half)]


def bootstrap_pairs(records, repeats=4000):
    # Paired games share fleets/agent randomness: bootstrap clusters, not games.
    groups = {}
    for row in records:
        groups.setdefault(row["seed"], []).append(int(row["winner"] == 0))
    values = [statistics.mean(v) for v in groups.values()]
    rng = random.Random(991827)
    estimates = sorted(statistics.mean(rng.choices(values, k=len(values))) for _ in range(repeats))
    return [estimates[int(.025*repeats)], estimates[int(.975*repeats)]] if values else [0, 1]


def summarize(records):
    wins = sum(r["winner"] == 0 for r in records)
    latency = [x for r in records for x in r["latency_ms"][0]]
    latency.sort()
    faults = [f for r in records for f in r["faults"]]
    return {"games": len(records), "independent_seeds": len({r["seed"] for r in records}),
            "wins": wins, "win_rate": wins/len(records),
            "paired_bootstrap_95ci": bootstrap_pairs(records),
            "first_win_rate": statistics.mean(r["winner"] == 0 for r in records if r["first"] == 0),
            "second_win_rate": statistics.mean(r["winner"] == 0 for r in records if r["first"] == 1),
            "faults": len(faults), "illegal_actions": sum(f["type"] == "ValueError" for f in faults),
            "timeouts": sum(f["type"] == "TimeoutError" for f in faults),
            "action_ms_mean": statistics.mean(latency) if latency else 0,
            "action_ms_p95": latency[int(.95*(len(latency)-1))] if latency else 0,
            "action_ms_max": max(latency, default=0)}


def _match_task(args):
    names, seed, first, style, limit = args
    return play(names, seed, first, style, time_limit_ms=limit)[0]


def evaluate(candidate, opponents, pairs, seed_start, styles, out, workers=1, time_limit_ms=1000):
    start = time.perf_counter()
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    summary = {"candidate": candidate, "rules": Rules().to_dict(), "seed_start": seed_start,
               "pairs_per_cell": pairs, "time_limit_ms": time_limit_ms,
               "timing_enforcement": "trusted in-process bots: measured after return; external adapter uses hard deadline",
               "python": platform.python_version(), "platform": platform.platform(),
               "workers": workers, "logical_cpus": os.cpu_count(), "results": []}
    root = Path(__file__).resolve().parent.parent
    summary["source_sha256"] = {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                                for p in sorted((root / "battleship").glob("*.py"))}
    summary["policies_sha256"] = {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                                  for p in sorted((root / "policies").glob("*.json"))}
    for opponent in opponents:
        for style in styles:
            tasks = [((candidate, opponent), seed_start+i, first, style, time_limit_ms)
                     for i in range(pairs) for first in (0, 1)]
            if workers > 1:
                with ProcessPoolExecutor(max_workers=workers) as pool:
                    rows = list(pool.map(_match_task, tasks, chunksize=2))
            else:
                rows = list(map(_match_task, tasks))
            name = f"{Path(opponent.removeprefix('exec:')).stem}-{style}"
            save_json(out / (name + ".json"), rows)
            entry = {"opponent": opponent, "style": style, **summarize(rows)}
            summary["results"].append(entry)
            summary["wall_seconds"] = time.perf_counter() - start
            save_json(out / "summary.json", summary)
            print(json.dumps(entry, ensure_ascii=False), flush=True)
    return summary


def attack_trial(name, seed, style="uniform", policy=None, rules=Rules()):
    target = Target(deploy(random.Random(seed_for(seed, "attack-board", style)), rules, style), rules)
    bot = make_bot(name, policy)
    bot.reset(rules.to_dict(), seed_for(seed, "attack-agent"))
    times, methods = [], {}
    while not target.done:
        start = time.perf_counter()
        target.fire(bot.act(target.observation()))
        times.append((time.perf_counter()-start)*1000)
        method = getattr(bot, "diagnostics", {}).get("method", name)
        methods[method] = methods.get(method, 0)+1
    return {"seed": seed, "style": style, "shots": target.shots.bit_count(),
            "ms": sum(times), "max_ms": max(times), "methods": methods}


def _attack_task(args):
    name, seed, style, p = args
    return attack_trial(name, seed, style, Policy(**p) if p else None)


def benchmark(name, seeds, styles=("uniform",), policy=None, workers=1):
    tasks = [(name, seed, style, asdict(policy) if policy else None) for seed in seeds for style in styles]
    if workers > 1:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            rows = list(pool.map(_attack_task, tasks, chunksize=4))
    else:
        rows = list(map(_attack_task, tasks))
    shots = [r["shots"] for r in rows]
    return {"mean_shots": statistics.mean(shots), "stdev": statistics.stdev(shots) if len(shots)>1 else 0,
            "boards": len(shots), "mean_ms_per_board": statistics.mean(r["ms"] for r in rows),
            "max_action_ms": max(r["max_ms"] for r in rows), "rows": rows}
