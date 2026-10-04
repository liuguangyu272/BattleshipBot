from dataclasses import asdict, replace
from pathlib import Path
import random
import statistics
import sys
import time
from concurrent.futures import ProcessPoolExecutor
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from battleship.bots import Policy, make_bot
from battleship.arena import benchmark
from battleship.core import Rules, Target, seed_for, save_json


def defense_trial(args):
    seed, count, style = args
    policy=Policy(mode='density',defense_candidates=count,deployment=style)
    defender=make_bot('density',policy)
    defender.reset(Rules().to_dict(),seed_for(seed,'defense'))
    start=time.perf_counter()
    fleet=defender.place()
    ms=(time.perf_counter()-start)*1000
    results={}
    for name in ['hunt','density','admiral']:
        attacker=make_bot(name)
        attacker.reset(Rules().to_dict(),seed_for(seed,'held-out-attacker',name))
        board=Target(fleet)
        while not board.done:
            board.fire(attacker.act(board.observation()))
        results[name]=board.shots.bit_count()
    return {'seed':seed,'selection_candidates':count,'style':style,'placement_ms':ms,'attacker_shots':results}


def run():
    root=Path('policies/endgame-defense')
    base=Policy.load('policies/hunt-search/best.json')
    rows=[]
    for mode, limit in [('density',0),('density',6),('density',10),('density',14),('hybrid',10),('constraint',10)]:
        p=replace(base,mode=mode,endgame_limit=limit)
        result=benchmark('admiral',range(33000,33300),('uniform','edge','cluster','spread'),p,4)
        rows.append({'mode':mode,'endgame_limit':limit,'policy':asdict(p),**result})
        save_json(root/'endgame.json',rows)
        print(f'endgame {mode} {limit}: {result["mean_shots"]:.3f}, maxms={result["max_action_ms"]:.2f}',flush=True)
    best=min(rows,key=lambda r:r['mean_shots'])
    Policy(**best['policy']).save(root/'attack-best.json')
    defense=[]
    for count,style in [(0,'uniform'),(0,'mixed'),(0,'edge'),(4,'mixed'),(8,'mixed'),(12,'mixed')]:
        tasks=[(seed,count,style) for seed in range(34000,34200)]
        with ProcessPoolExecutor(max_workers=4) as pool:
            data=list(pool.map(defense_trial,tasks,chunksize=4))
        row={'candidates':count,'style':style,'mean_shots':{name:statistics.mean(r['attacker_shots'][name] for r in data) for name in ['hunt','density','admiral']},
             'mean_placement_ms':statistics.mean(r['placement_ms'] for r in data),'max_placement_ms':max(r['placement_ms'] for r in data),'rows':data}
        defense.append(row)
        save_json(root/'defense.json',defense)
        print(f'defense {count} {style}: {row["mean_shots"]}, maxms={row["max_placement_ms"]:.1f}',flush=True)


if __name__=='__main__':
    run()
