"""A second, robustness-first search. Never reads the v1 or v2 final test sets."""
from dataclasses import asdict, replace
from pathlib import Path
import argparse
import statistics
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from battleship.arena import benchmark
from battleship.bots import Policy
from battleship.core import save_json

STYLES = ('uniform', 'edge', 'cluster', 'spread')
ROOT = Path('policies/refine-v2')


def per_style(rows):
    return {s: statistics.mean(r['shots'] for r in rows if r['style'] == s) for s in STYLES}


def score(row, baseline):
    # Penalize the worst regression in addition to the mean: don't buy a large
    # edge-only gain by making uniformly deployed or clustered fleets easier.
    differences = [row['per_style'][s] - baseline['per_style'][s] for s in STYLES]
    return statistics.mean(differences) + max(0, max(differences))


def run(boards=160, workers=4):
    variants = [Policy(mode='density', deployment='mixed', defense_candidates=12),
                Policy.load('policies/champion.json')]
    for length, parity, edge in [(0,.25,0), (0,.5,0), (1,.25,0), (1,.5,0),
                                 (2,.25,0), (2,.5,0), (0,.25,.05), (1,.25,.05),
                                 (2,.25,.05), (1,.25,.1), (2,.25,.1), (0,0,.05)]:
        variants.append(Policy(mode='density', length_power=length, parity_bonus=parity,
                               edge_bias=edge, deployment='mixed', defense_candidates=12))
    rows = []
    for i, p in enumerate(variants):
        result = benchmark('admiral', range(60000, 60000+boards), STYLES, p, workers)
        row = {'trial': i, 'policy': asdict(p), **result, 'per_style': per_style(result['rows'])}
        rows.append(row)
        row['robust_score'] = score(row, rows[0])
        p.save(ROOT/f'trial-{i:02d}.json')
        save_json(ROOT/'development.json', rows)
        print(f"v2 dev {i}: mean={result['mean_shots']:.3f}, robust={row['robust_score']:.3f}, {row['per_style']}", flush=True)
    finalists = sorted(rows[2:], key=lambda r: r['robust_score'])[:3]
    validation = []
    for row in rows[:2] + finalists:
        p = Policy(**row['policy'])
        result = benchmark('admiral', range(70000, 70400), STYLES, p, workers)
        v = {'trial': row['trial'], 'policy': asdict(p), **result, 'per_style': per_style(result['rows'])}
        validation.append(v)
        v['robust_score'] = score(v, validation[0])
        save_json(ROOT/'validation.json', validation)
        print(f"v2 validation {row['trial']}: mean={v['mean_shots']:.3f}, robust={v['robust_score']:.3f}, {v['per_style']}", flush=True)
    best = min(validation, key=lambda r:r['robust_score'])
    Policy(**best['policy']).save(ROOT/'best.json')
    save_json(ROOT/'manifest.json', {'development_seeds':[60000,60000+boards-1],
              'validation_seeds':[70000,70399], 'styles':list(STYLES),
              'objective':'mean delta vs baseline plus positive worst-style delta',
              'selected_trial':best['trial'], 'final_seeds_reserved':[1600000,1699999]})


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--boards',type=int,default=160)
    parser.add_argument('--workers',type=int,default=4)
    args=parser.parse_args()
    run(args.boards,args.workers)
