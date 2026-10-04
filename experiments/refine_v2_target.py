"""Controlled hunt-only edge ablation, selected before opening new test seeds."""
from dataclasses import asdict, replace
from pathlib import Path
import json
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from battleship.arena import benchmark
from battleship.bots import Policy
from battleship.core import save_json
from experiments.refine_v2 import STYLES, per_style, score


def run():
    root=Path('policies/refine-v2')
    prior=json.loads((root/'validation.json').read_text())
    baseline=prior[0]
    rows=[]
    variants=[replace(Policy(**v['policy']),target_edge_scale=0) for v in prior if v['trial'] not in (0,1)]
    variants += [Policy(mode='density',length_power=1,edge_bias=.1,target_edge_scale=0,
                        target_power=2,sink_bonus=1,defense_candidates=12),
                 Policy(mode='density',length_power=1,edge_bias=.05,target_edge_scale=0,
                        target_power=2,sink_bonus=1,defense_candidates=12)]
    original=Policy.load('policies/champion.json')
    variants += [replace(original,target_edge_scale=0,edge_bias=edge,length_power=length)
                 for edge,length in [(.2,5),(.1,2),(.05,1)]]
    for i,p in enumerate(variants):
        result=benchmark('admiral',range(70000,70400),STYLES,p,4)
        row={'trial':f'target-{i}','policy':asdict(p),**result,'per_style':per_style(result['rows'])}
        row['robust_score']=score(row,baseline)
        rows.append(row)
        p.save(root/f'target-{i}.json')
        save_json(root/'target-validation.json',rows)
        print(f"target {i}: {row['mean_shots']:.3f}, robust={row['robust_score']:.3f}, {row['per_style']}",flush=True)
    winner=min(prior+rows,key=lambda r:r['robust_score'])
    Policy(**winner['policy']).save('policies/champion-v2.json')
    save_json(root/'selection.json',{'selected':winner['trial'],'policy':winner['policy'],
        'validation_seeds':[70000,70399],'objective':'mean delta + positive worst-style delta vs density',
        'final_test_seeds':[1600000,1600399],'final_styles':list(STYLES),
        'final_comparisons':['champion-v1','density'],'held_out_not_used_for_selection':True})


if __name__=='__main__':run()
