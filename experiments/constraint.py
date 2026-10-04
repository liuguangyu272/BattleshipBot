from dataclasses import asdict
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from battleship.bots import Policy
from battleship.arena import benchmark
from battleship.core import save_json


def run():
    root = Path("policies/constraint")
    rows = []
    variants = [Policy(mode="constraint", hunt_power=h, parity_bonus=p, target_bonus=t, sink_bonus=s)
                for h, p, t, s in [(0,.5,0,.15),(1,.5,0,.15),(1,.5,1,.15),(1,.5,2,.15),
                                    (0,.5,1,.5),(0,1,0,.15),(0,.15,0,0),(1,.15,0,0)]]
    for i, policy in enumerate(variants):
        result = benchmark("admiral", range(11000, 11150), ("uniform", "edge", "cluster", "spread"), policy, 4)
        rows.append({"trial":i,"policy":asdict(policy),**result})
        save_json(root/"search.json", rows)
        policy.save(root/f"trial-{i:02d}.json")
        print(f"constraint {i}: shots={result['mean_shots']:.3f}, ms={result['mean_ms_per_board']:.1f}",flush=True)
    validation=[]
    for row in sorted(rows,key=lambda r:r["mean_shots"])[:3]:
        result=benchmark("admiral",range(31000,31300),("uniform","edge","cluster","spread"),Policy(**row["policy"]),4)
        validation.append({"trial":row["trial"],"policy":row["policy"],**result})
        save_json(root/"validation.json", validation)
        print(f"constraint validation {row['trial']}: {result['mean_shots']:.3f}",flush=True)
    best=min(validation,key=lambda r:r["mean_shots"])
    Policy(**best['policy']).save(root/'best.json')


if __name__ == '__main__':
    run()
