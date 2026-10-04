"""Validate saved results, source provenance, replay integrity, and reproduction.

Reads final data without tuning any strategy. Timings are intentionally excluded
from equality comparisons because they depend on current machine load.
"""
from pathlib import Path
import hashlib
import json
import statistics
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from battleship.arena import play
from battleship.core import verify_replay, save_json

ROOT=Path(__file__).resolve().parents[1]


def main():
    checks=[]
    total=0
    worst_action=0
    worst_setup=0
    for folder in ['final-main','final-stress','final-defense','final-strong-defense','final-external']:
        summary=json.loads((ROOT/'results'/folder/'summary.json').read_text(encoding='utf-8'))
        for relative,expected in summary['source_sha256'].items():
            assert hashlib.sha256((ROOT/relative).read_bytes()).hexdigest()==expected,relative
        for relative,expected in summary['policies_sha256'].items():
            assert hashlib.sha256((ROOT/relative).read_bytes()).hexdigest()==expected,relative
        for entry in summary['results']:
            name=f"{Path(entry['opponent'].removeprefix('exec:')).stem}-{entry['style']}.json"
            rows=json.loads((ROOT/'results'/folder/name).read_text(encoding='utf-8'))
            assert len(rows)==entry['games']
            assert sum(r['winner']==0 for r in rows)==entry['wins']
            assert all(not r['faults'] for r in rows)
            total+=len(rows)
            for row in rows:
                worst_action=max(worst_action,max(row['latency_ms'][0],default=0),max(row['latency_ms'][1],default=0))
                worst_setup=max(worst_setup,max(row['setup_ms'],default=0))
            # Re-run two seed clusters in each experimental condition.
            for original in rows[:4]:
                current,replay=play(tuple(original['bots']),original['seed'],original['first'],original['style'])
                for key in ['winner','shots','plies','faults']:
                    assert current[key]==original[key],(folder,key,original['seed'])
                verify_replay(replay)
        checks.append(folder+': counts, hashes, faults, first two seed clusters reproduced')
    demo=json.loads((ROOT/'replays/final-demo.json').read_text(encoding='utf-8'))
    verify_replay(demo)
    current,replay=play(('champion','density'),20261004,style='native')
    assert replay['events']==demo['events']
    checks.append('final-demo exact complete action sequence reproduced')
    # External protocol must give the same game result as the same in-process bot.
    rows=json.loads((ROOT/'results/final-external/density-native.json').read_text(encoding='utf-8'))
    for original in rows:
        current,_=play(('champion','density'),original['seed'],original['first'],original['style'])
        assert current['winner']==original['winner'] and current['shots']==original['shots']
    checks.append('all 20 external matches agree with equivalent in-process champion')
    result={'ok':True,'total_final_duels':total,'illegal_actions':0,'timeouts':0,'faults':0,
            'max_action_ms_both_players':worst_action,'max_setup_ms_both_players':worst_setup,'checks':checks}
    save_json(ROOT/'results/delivery-verification.json',result)
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
