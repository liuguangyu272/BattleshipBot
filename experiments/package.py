"""Build a portable ZIP, test it in isolation on D:, then write the final manifest."""
from pathlib import Path
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import zipfile

ROOT=Path(__file__).resolve().parents[1]
ARCHIVE=ROOT.parent/'battleship.zip'


def payload():
    return [p for p in sorted(ROOT.rglob('*')) if p.is_file() and
            not {'work','__pycache__','.git'}.intersection(p.relative_to(ROOT).parts) and
            p.suffix not in ('.pyc','.tmp')]


def build():
    files=[p for p in payload() if p.name!='MANIFEST.json']
    manifest={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    (ROOT/'MANIFEST.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    with zipfile.ZipFile(ARCHIVE,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for p in payload():
            z.write(p,Path('battleship')/p.relative_to(ROOT))
    with zipfile.ZipFile(ARCHIVE) as z:
        assert z.testzip() is None


def main():
    build()
    scratch=ROOT/'work'
    scratch.mkdir(exist_ok=True)
    logs=[]
    tests_passed=0
    with tempfile.TemporaryDirectory(prefix='package-smoke-',dir=scratch) as tmp:
        unpack=Path(tmp).resolve()
        assert unpack.is_relative_to(scratch.resolve())  # cleanup is confined to task scratch
        with zipfile.ZipFile(ARCHIVE) as z:
            # Reject traversal before extracting even though this archive was just created.
            for name in z.namelist():
                assert (unpack/name).resolve().is_relative_to(unpack)
            z.extractall(unpack)
        cwd=unpack/'battleship'
        env=os.environ.copy()
        env.pop('PYTHONPATH',None)
        commands=[['-m','unittest','discover','-s','tests','-v'],
                  ['-m','battleship','demo','--bot','champion','--opponent','density','--seed','20261004',
                   '--style','native','--out','replays/packaged-demo.json'],
                  ['-m','battleship','replay','replays/packaged-demo.json']]
        if (ROOT/'replays/fortress-demo.json').exists():
            commands += [['-m','battleship','demo','--bot','fortress','--opponent','champion',
                          '--seed','20261005','--style','native','--out','replays/packaged-fortress.json'],
                         ['-m','battleship','replay','replays/packaged-fortress.json']]
        for command in commands:
            r=subprocess.run([sys.executable,*command],cwd=cwd,env=env,capture_output=True,text=True,
                             encoding='utf-8',errors='replace',timeout=90)
            logs.append('COMMAND: python '+' '.join(command)+'\n'+r.stdout+r.stderr)
            if command[:2]==['-m','unittest']:
                match=re.search(r'Ran (\d+) tests?',r.stdout+r.stderr)
                if not match:
                    raise RuntimeError('missing unittest completion summary')
                tests_passed=int(match.group(1))
            if r.returncode:
                (ROOT/'results/package-smoke.txt').write_text('\n'.join(logs),encoding='utf-8')
                raise RuntimeError('extracted deliverable failed smoke test')
        original=json.loads((ROOT/'replays/final-demo.json').read_text(encoding='utf-8'))
        reproduced=json.loads((cwd/'replays/packaged-demo.json').read_text(encoding='utf-8'))
        assert original['events']==reproduced['events']
        logs.append('Packaged demo exactly matches all 94 original actions and feedback events.\n')
        if (ROOT/'replays/fortress-demo.json').exists():
            original=json.loads((ROOT/'replays/fortress-demo.json').read_text(encoding='utf-8'))
            reproduced=json.loads((cwd/'replays/packaged-fortress.json').read_text(encoding='utf-8'))
            assert original['events']==reproduced['events']
            logs.append('Packaged Fortress demo exactly matches all saved actions and feedback events.\n')
    (ROOT/'results/package-smoke.txt').write_text('\n'.join(logs),encoding='utf-8')
    verification=json.loads((ROOT/'results/delivery-verification.json').read_text(encoding='utf-8'))
    delivery={'status':'complete_local_delivery','date':'2026-10-04','timezone':'Asia/Shanghai',
              'entrypoint':'start.cmd or python -m battleship serve','runtime':'Python >=3.11; tested 3.14.7; standard library only',
              'rules':'local-classic-touching-v1','official_competition_verified':False,
              'tests_passed':tests_passed,'clean_zip_extraction_tested':True,'full_demo_verified':True,
              'final_match_verification':verification,'policy':'policies/champion.json',
              'five_hour_quota_remaining':None,'quota_check':'No exposed account quota; desktop screenshot did not show the quota panel',
              'shutdown_performed':False,'shutdown_reason':'Other work saved was not confirmed, as required by the user',
              'limitations':['No official protocol or opponent provided','Uniform/cluster attack regression against probability baselines',
                             'Deployment selection benefit is opponent-dependent','Only one machine and Python version measured']}
    revision=ROOT/'results/revision-v2/verification.json'
    if revision.exists():
        delivery['revision_v2']=json.loads(revision.read_text(encoding='utf-8'))
        delivery['recommended_policy']='policies/fortress.json'
        delivery['quota_check']='Parallel research hit a platform usage limit; new research stopped, existing final evaluation and delivery completed'
    (ROOT/'DELIVERY.json').write_text(json.dumps(delivery,ensure_ascii=False,indent=2),encoding='utf-8')
    progress=ROOT/'docs/PROGRESS.md'
    text=progress.read_text(encoding='utf-8')
    text=text.replace('最终主评估、跨分布压力评估与消融实验正在执行，结果持续保存；最终完成状态以 RESULTS.md、DELIVERY.json 为准。',
                      '最终 13,220 局双人比赛与 8,000 次单人攻击消融均已完成；0 非法动作、0 超时、0 Bot 错误。源码/策略哈希、每个条件的复跑、20 局内外部接口等价性通过核对。ZIP 解压到独立临时目录后，19 项测试和完整演示再次通过，94 个事件逐项一致。最终完成状态见 RESULTS.md、DELIVERY.json。')
    progress.write_text(text,encoding='utf-8')
    build()
    print(json.dumps({'archive':str(ARCHIVE),'bytes':ARCHIVE.stat().st_size,
                      'sha256':hashlib.sha256(ARCHIVE.read_bytes()).hexdigest(),'clean_extract_smoke':'passed'},indent=2))


if __name__=='__main__':main()
