"""Reproduce the frozen final protocol in a fresh results directory."""
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]


def run(*args):
    subprocess.run([sys.executable,'-m','battleship',*args],cwd=ROOT,check=True)


if __name__=='__main__':
    run('evaluate','--bot','champion','--opponents','random','hunt','density','admiral',
        '--pairs','500','--seed-start','900000','--styles','uniform','native','--workers','4',
        '--out','results/reproduced/main')
    run('evaluate','--bot','champion','--opponents','hunt','density','admiral',
        '--pairs','200','--seed-start','910000','--styles','edge','cluster','spread','--workers','4',
        '--out','results/reproduced/stress')
    run('evaluate','--bot','champion','--opponents','policies/attack-only.json',
        '--pairs','500','--seed-start','930000','--styles','native','--workers','4',
        '--out','results/reproduced/defense')
    run('evaluate','--bot','champion','--opponents','policies/defended-density.json',
        '--pairs','300','--seed-start','940000','--styles','native','--workers','4',
        '--out','results/reproduced/strong-defense')
    run('evaluate','--bot','exec:examples/external-bot.json','--opponents','density',
        '--pairs','10','--seed-start','950000','--styles','native','--workers','2',
        '--out','results/reproduced/external')
    run('demo','--bot','champion','--opponent','density','--seed','20261004','--style','native',
        '--out','results/reproduced/demo.json')
    run('replay','results/reproduced/demo.json')
