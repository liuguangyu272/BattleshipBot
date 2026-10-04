"""Reproducible development only; never touches the v1 final evaluation seeds."""
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, replace
import argparse
import hashlib
import json
from pathlib import Path
import random
import statistics
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from battleship.bots import Policy, PosteriorBot
from battleship.context_bot import ContextBot, ContextConfig
from battleship.core import Rules, Target, deploy, seed_for, save_json

ROOT = Path(__file__).resolve().parents[1]
STYLES = ("uniform", "edge", "cluster", "spread")


def _trial(task):
    seed, style, context, policy = task
    rules = Rules()
    target = Target(deploy(random.Random(seed_for(seed, "attack-board", style)), rules, style), rules)
    bot = ContextBot(Policy(**policy), ContextConfig(**context)) if context else PosteriorBot(Policy(**policy))
    bot.reset(rules.to_dict(), seed_for(seed, "attack-agent"))
    times = []
    while not target.done:
        start = time.perf_counter()
        action = bot.act(target.observation())
        times.append((time.perf_counter() - start) * 1000)
        target.fire(action)
    return {"seed": seed, "style": style, "shots": target.shots.bit_count(),
            "ms": sum(times), "max_ms": max(times), "faults": 0,
            "last_weights": getattr(bot, "last_model_weights", {})}


def benchmark(config, policy, seeds, workers):
    tasks = [(seed, style, asdict(config) if config else None, asdict(policy)) for seed in seeds for style in STYLES]
    with ProcessPoolExecutor(max_workers=workers) as pool:
        rows = list(pool.map(_trial, tasks, chunksize=4))
    return {"context": asdict(config) if config else None,
            "policy": asdict(policy), "boards": len(rows),
            "mean_shots": statistics.mean(row["shots"] for row in rows),
            "by_style": {style: statistics.mean(r["shots"] for r in rows if r["style"] == style) for style in STYLES},
            "max_action_ms": max(row["max_ms"] for row in rows),
            "mean_board_ms": statistics.mean(row["ms"] for row in rows), "rows": rows}


def compare(result, baseline):
    old = {(r["seed"], r["style"]): r["shots"] for r in baseline["rows"]}
    groups = {}
    for row in result["rows"]:
        groups.setdefault(row["seed"], []).append(row["shots"] - old[row["seed"], row["style"]])
    paired = [statistics.mean(values) for values in groups.values()]
    rng = random.Random(4528)
    samples = sorted(statistics.mean(rng.choices(paired, k=len(paired))) for _ in range(2000))
    return {"mean_delta": statistics.mean(paired), "paired_ci95": [samples[50], samples[1950]],
            "style_delta": {s: result["by_style"][s] - baseline["by_style"][s] for s in STYLES}}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=("smoke", "dev", "validate"), default="dev")
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    output = ROOT / "results" / "revision-v2"
    policies = ROOT / "policies" / "context-v2"
    output.mkdir(parents=True, exist_ok=True)
    policies.mkdir(parents=True, exist_ok=True)
    policy = Policy.load(ROOT / "policies" / "champion.json")
    if args.phase == "validate":
        manifest = json.loads((policies / "selected.json").read_text())
        configs = [("selected", ContextConfig(**manifest["context"]))]
        seeds = range(81000, 81400)
    else:
        seeds = range(80000, 80016 if args.phase == "smoke" else 80200)
        base = ContextConfig()
        configs = [("full-l2", base), ("full-l0", replace(base, length_power=0)),
                   ("half-l2", replace(base, mix=.5)), ("full-l1", replace(base, length_power=1)),
                   ("soft-l1", replace(base, temperature=.35, length_power=1)),
                   ("strong-l1", replace(base, temperature=1, uniform_floor=.05, length_power=1))]
    baseline_path = output / f"context-{args.phase}-baseline.json"
    start = time.perf_counter()
    baseline = benchmark(None, policy, seeds, args.workers)
    save_json(baseline_path, baseline)
    print(json.dumps({"phase": args.phase, "name": "champion-v1", "mean": baseline["mean_shots"],
                      "style": baseline["by_style"]}), flush=True)
    results = []
    for name, config in configs:
        result = benchmark(config, policy, seeds, args.workers)
        result.update(name=name, comparison=compare(result, baseline))
        save_json(output / f"context-{args.phase}-{name}.json", result)
        results.append({k: v for k, v in result.items() if k != "rows"})
        ContextBot(policy, config).save(policies / f"{name}.json")
        save_json(output / f"context-{args.phase}-summary.json", results)
        print(json.dumps({k: result[k] for k in ("name", "mean_shots", "by_style", "comparison", "max_action_ms")}), flush=True)
    if args.phase == "dev":
        best = min(results, key=lambda r: r["comparison"]["mean_delta"] + .25 * max(0, max(r["comparison"]["style_delta"].values())))
        save_json(policies / "selected.json", {"kind": "context", "policy": asdict(policy), "context": best["context"], "name": best["name"]})
    save_json(output / f"context-{args.phase}-manifest.json", {
        "phase": args.phase, "seed_start": seeds.start, "seed_stop_exclusive": seeds.stop,
        "styles": STYLES, "workers": args.workers, "seconds": time.perf_counter() - start,
        "source_sha256": {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                          for name in ("battleship/context_bot.py", "battleship/bots.py", "experiments/context_search.py")}})


if __name__ == "__main__":
    main()
