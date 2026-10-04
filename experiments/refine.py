"""Second development experiment; never reads final evaluation seeds."""
from dataclasses import asdict, replace
from pathlib import Path
import json
import random
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from battleship.bots import Policy
from battleship.arena import benchmark
from battleship.core import save_json


def run():
    root = Path("policies/refine")
    root.mkdir(parents=True, exist_ok=True)
    variants = []
    for power in (0, .5, 1):
        for parity in (0, .15, .5):
            variants.append(Policy(mode="density", hunt_power=power, parity_bonus=parity))
    for samples in (256, 1024):
        for bonus in (0, 1, 4):
            for mix in (.5, 1):
                variants.append(Policy(hunt_power=1, samples=samples, target_bonus=bonus,
                                       joint_mix=mix, parity_bonus=.15))
    history = []
    for i, policy in enumerate(variants):
        result = benchmark("admiral", range(11000, 11150), ("uniform", "edge", "cluster", "spread"), policy, 4)
        row = {"trial": i, "policy": asdict(policy), **result}
        history.append(row)
        save_json(root / "search.json", history)
        policy.save(root / f"trial-{i:02d}.json")
        print(f"trial={i} mean={result['mean_shots']:.3f} ms={result['mean_ms_per_board']:.1f}", flush=True)
    finalists = sorted(history, key=lambda r: r["mean_shots"])[:4]
    validation = []
    for row in finalists:
        result = benchmark("admiral", range(31000, 31300), ("uniform", "edge", "cluster", "spread"), Policy(**row["policy"]), 4)
        validation.append({"trial": row["trial"], "policy": row["policy"], **result})
        save_json(root / "validation.json", validation)
        print(f"validation trial={row['trial']} mean={result['mean_shots']:.3f}", flush=True)
    best = min(validation, key=lambda r:r["mean_shots"])
    Policy(**best["policy"]).save(root / "best.json")
    save_json(root / "manifest.json", {"dev": [11000,11149], "validation": [31000,31299],
              "final_reserved": [900000,999999], "selected": best["trial"]})


if __name__ == "__main__":
    run()
