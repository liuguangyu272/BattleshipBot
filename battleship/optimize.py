"""Common-random-number parameter search. Dev and validation seeds are disjoint."""
from dataclasses import asdict, replace
from pathlib import Path
import random

from .arena import benchmark
from .bots import Policy
from .core import save_json


def optimize(out, trials=12, boards=80, workers=1, seed=20261004):
    root = Path(out)
    root.mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed)
    variants = [Policy(), Policy(mode="density", deployment="uniform"),
                Policy(hunt_power=1), Policy(samples=256), Policy(joint_mix=.5),
                Policy(mode="joint", samples=256)]
    while len(variants) < trials:
        variants.append(Policy(hunt_power=rng.choice([0, .5, 1]),
                               target_power=rng.choice([2, 3, 5]),
                               samples=rng.choice([64, 128, 256]),
                               sink_bonus=rng.choice([0, .15, .5]),
                               joint_mix=rng.choice([.5, .8, 1]),
                               parity_bonus=rng.choice([0, .1, .3])))
    history = []
    for i, policy in enumerate(variants[:trials]):
        result = benchmark("admiral", range(10000, 10000+boards), ("uniform", "edge", "cluster"), policy, workers)
        row = {"trial": i, "policy": asdict(policy), **result}
        history.append(row)
        policy.save(root / f"trial-{i:02d}.json")
        save_json(root / "search.json", history)
        print(f"trial={i} dev mean shots={result['mean_shots']:.3f}, ms/board={result['mean_ms_per_board']:.1f}", flush=True)
    finalists = sorted(history, key=lambda r: r["mean_shots"])[:min(3, len(history))]
    validation = []
    for row in finalists:
        policy = Policy(**row["policy"])
        result = benchmark("admiral", range(30000, 30000+boards), ("uniform", "edge", "cluster", "spread"), policy, workers)
        validation.append({"trial": row["trial"], "policy": asdict(policy), **result})
        print(f"validation trial={row['trial']} mean shots={result['mean_shots']:.3f}", flush=True)
        save_json(root / "validation.json", validation)
    best = min(validation, key=lambda r: r["mean_shots"])
    Policy(**best["policy"]).save(root / "best.json")
    save_json(root / "manifest.json", {"search_seed": seed, "dev_seed_range": [10000, 10000+boards-1],
              "validation_seed_range": [30000, 30000+boards-1], "selected_trial": best["trial"],
              "selection": "minimum validation mean shots across four deployment styles",
              "final_test_seed_range_reserved": [900000, 999999], "trials": trials, "boards_per_style": boards})
    return best
