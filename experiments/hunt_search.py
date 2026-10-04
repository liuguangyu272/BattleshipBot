"""Search search/target weighting, then validate finalists on new boards."""
from dataclasses import asdict
from pathlib import Path
import random
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from battleship.bots import Policy
from battleship.arena import benchmark
from battleship.core import save_json


def run():
    root=Path('policies/hunt-search')
    rng=random.Random(782)
    variants=[Policy(mode='density')]
    for i in range(47):
        variants.append(Policy(mode='density',hunt_power=rng.choice([0,1]),
            length_power=rng.choice([0,1,2,3,5]),parity_bonus=rng.choice([0,.2,.5,1,3]),
            edge_bias=rng.choice([0,.05,.1,.2]),target_power=rng.choice([1,2,3,5]),sink_bonus=rng.choice([0,.2,.5,1])))
    rows=[]
    for i,p in enumerate(variants):
        r=benchmark('admiral',range(12000,12200),('uniform','edge','cluster','spread'),p,4)
        rows.append({'trial':i,'policy':asdict(p),**r})
        p.save(root/f'trial-{i:02d}.json')
        save_json(root/'search.json',rows)
        print(f'hunt {i}: {r["mean_shots"]:.3f}',flush=True)
    validation=[]
    for row in sorted(rows,key=lambda r:r['mean_shots'])[:5]:
        r=benchmark('admiral',range(32000,32500),('uniform','edge','cluster','spread'),Policy(**row['policy']),4)
        validation.append({'trial':row['trial'],'policy':row['policy'],**r})
        save_json(root/'validation.json',validation)
        print(f'validate hunt {row["trial"]}: {r["mean_shots"]:.3f}',flush=True)
    best=min(validation,key=lambda r:r['mean_shots'])
    Policy(**best['policy']).save(root/'best.json')


if __name__=='__main__':
    run()
