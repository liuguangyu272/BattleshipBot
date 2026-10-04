"""Test robust private deployment selection against unseen attack random streams."""
from dataclasses import replace, asdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
import statistics
import sys
import time

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from battleship.bots import Policy, make_bot
from battleship.core import Rules, Target, seed_for, save_json


def trial(args):
    seed, fields = args
    policy=Policy(**fields)
    defender=make_bot('champion',policy)
    defender.reset(Rules().to_dict(),seed_for(seed,'v2-defense'))
    start=time.perf_counter()
    fleet=defender.place()
    ms=(time.perf_counter()-start)*1000
    costs={}
    for name in ('density','champion','balanced'):
        attacker=make_bot(name)
        attacker.reset(Rules().to_dict(),seed_for(seed,'v2-independent-attacker',name))
        board=Target(fleet)
        while not board.done:
            board.fire(attacker.act(board.observation()))
        costs[name]=board.shots.bit_count()
    return {'seed':seed,'placement_ms':ms,'shots':costs}


def run():
    base=Policy.load('policies/champion.json')
    policies=[base,replace(base,defense_mode='robust',defense_candidates=12),
              replace(base,defense_mode='robust',defense_candidates=32),
              replace(base,defense_mode='robust',defense_candidates=64)]
    history=[]
    for i,p in enumerate(policies):
        with ProcessPoolExecutor(max_workers=4) as pool:
            rows=list(pool.map(trial,[(s,asdict(p)) for s in range(85000,85200)],chunksize=2))
        entry={'trial':i,'policy':asdict(p),'mean_shots':{name:statistics.mean(r['shots'][name] for r in rows)
              for name in ('density','champion','balanced')},
              'max_placement_ms':max(r['placement_ms'] for r in rows),'rows':rows}
        history.append(entry)
        p.save(f'policies/defense-v2/trial-{i}.json')
        save_json('policies/defense-v2/validation.json',history)
        print(f"defense v2 {i}: {entry['mean_shots']} max={entry['max_placement_ms']:.1f}ms",flush=True)
    viable=[r for r in history if r['max_placement_ms']<4000]
    best=max(viable,key=lambda r:min(r['mean_shots'].values()))
    Policy(**best['policy']).save('policies/fortress.json')
    save_json('policies/defense-v2/selection.json',{'selected':best['trial'],
        'validation_seeds':[85000,85199],'selection':'maximize worst held-out attacker mean survival; setup <4000ms',
        'final_seeds_reserved':[1620000,1620999]})


if __name__=='__main__':run()
