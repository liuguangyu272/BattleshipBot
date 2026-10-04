"""Frozen-policy held-out ablations; results must not be used to retune champion."""
from dataclasses import asdict, replace
from pathlib import Path
import random
import statistics
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from battleship.bots import Policy
from battleship.arena import benchmark
from battleship.core import save_json


def run():
    champion=Policy.load('policies/champion.json')
    variants=[('baseline_density',Policy(mode='density')),('tuned_density',replace(champion,mode='density',endgame_limit=0)),
              ('without_endgame',replace(champion,endgame_limit=0)),('champion',champion)]
    rows=[]
    root=Path('results/final-ablation')
    for name,p in variants:
        result=benchmark('admiral',range(920000,920500),('uniform','edge','cluster','spread'),p,4)
        rows.append({'name':name,'policy':asdict(p),**result})
        save_json(root/'results.json',rows)
        print(f'{name}: {result["mean_shots"]:.3f} shots, {result["mean_ms_per_board"]:.1f} ms/board',flush=True)
    base={(r['seed'],r['style']):r['shots'] for r in rows[0]['rows']}
    comparisons=[]
    for row in rows[1:]:
        differences={}
        for r in row['rows']:
            differences.setdefault(r['seed'],[]).append(r['shots']-base[(r['seed'],r['style'])])
        values=[statistics.mean(v) for v in differences.values()]
        rng=random.Random(986123)
        boot=sorted(statistics.mean(rng.choices(values,k=len(values))) for _ in range(4000))
        comparisons.append({'name':row['name'],'delta_shots_vs_baseline':statistics.mean(values),
                            'paired_seed_bootstrap_95ci':[boot[100],boot[3900]]})
    save_json(root/'comparisons.json',comparisons)


if __name__=='__main__':run()
