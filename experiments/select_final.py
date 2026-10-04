"""Last model selection on development-only data; final seeds remain untouched."""
from dataclasses import asdict, replace
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from battleship.bots import Policy
from battleship.arena import benchmark
from battleship.core import save_json


def run():
    root=Path('policies/final-selection')
    base=Policy.load('policies/hunt-search/best.json')
    candidates=[replace(base,mode=m,endgame_limit=e,samples=s,joint_mix=j,target_bonus=t)
                for m,e,s,j,t in [('density',0,128,1,0),('hybrid',10,128,1,0),
                                  ('adaptive',0,128,1,0),('adaptive',10,128,1,0),
                                  ('hybrid',6,256,.5,1),('constraint',6,128,.5,0),
                                  ('adaptive',6,128,.5,0)]]
    rows=[]
    for i,p in enumerate(candidates):
        result=benchmark('admiral',range(35000,35600),('uniform','edge','cluster','spread'),p,4)
        rows.append({'trial':i,'policy':asdict(p),**result})
        p.save(root/f'trial-{i}.json')
        save_json(root/'validation.json',rows)
        print(f'final select {i}: {result["mean_shots"]:.4f}, {result["mean_ms_per_board"]:.1f}ms/board',flush=True)
    winner=min(rows,key=lambda r:r['mean_shots'])
    selected=replace(Policy(**winner['policy']),defense_candidates=12)
    selected.save('policies/champion.json')
    save_json(root/'manifest.json',{'selected':winner['trial'],'validation_seeds':[35000,35599],
                                   'styles':['uniform','edge','cluster','spread'],'final_seeds_reserved':[900000,999999],
                                   'defense_selection':'12 candidates, selected on 34000..34199; see endgame-defense/defense.json'})


if __name__=='__main__':run()
