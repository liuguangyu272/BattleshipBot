"""Audit revision experiments and generate an evidence-based Chinese report."""
from pathlib import Path
import hashlib
import json
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from battleship.arena import play
from battleship.core import save_json, verify_replay

ROOT=Path(__file__).resolve().parents[1]


def read(path):
    return json.loads((ROOT/path).read_text(encoding='utf-8'))


def table(rows):
    lines=['| 对手 | 部署 | 对局 / 种子 | 胜率 | 配对 95% 区间 |','|---|---|---:|---:|---:|']
    for row in rows:
        lo,hi=row['paired_bootstrap_95ci']
        lines.append(f"| {row['opponent']} | {row['style']} | {row['games']} / {row['independent_seeds']} | {row['win_rate']:.2%} | {lo:.2%}–{hi:.2%} |")
    return '\n'.join(lines)


def main():
    fortress=read('results/revision-v2/fortress-final/summary.json')
    balanced=read('results/revision-v2/final/summary.json')
    native=read('results/revision-v2/native/summary.json')
    external=read('results/revision-v2/external/summary.json')
    assert len(fortress['results'])==3 and len(balanced['results'])==8 and len(native['results'])==2
    # The promoted strategy's final runtime source and policy must be unchanged.
    for key,expected in fortress['source_sha256'].items():
        assert hashlib.sha256((ROOT/key).read_bytes()).hexdigest()==expected,key
    for key,expected in fortress['policies_sha256'].items():
        assert hashlib.sha256((ROOT/key).read_bytes()).hexdigest()==expected,key
    total=0
    faults=[]
    max_action=max_setup=0
    for folder,summary in [('fortress-final',fortress),('final',balanced),('native',native),('external',external)]:
        for row in summary['results']:
            records=read(f"results/revision-v2/{folder}/{row['opponent']}-{row['style']}.json")
            assert len(records)==row['games']
            assert sum(r['winner']==0 for r in records)==row['wins']
            total+=len(records)
            for r in records:
                faults.extend(r['faults'])
                max_action=max(max_action,*(max(t,default=0) for t in r['latency_ms']))
                max_setup=max(max_setup,max(r['setup_ms'],default=0))
            # Two genuine replays per experimental cell, not just stored stats.
            for old in records[:2]:
                current,replay=play(tuple(old['bots']),old['seed'],old['first'],old['style'])
                for key in ['winner','shots','plies','faults']:
                    assert current[key]==old[key],(folder,key,old['seed'])
                verify_replay(replay)
    assert not faults
    result,replay=play(('fortress','champion'),20261005,style='native')
    assert not result['faults']
    verify_replay(replay)
    save_json(ROOT/'replays/fortress-demo.json',replay)
    ui=read('results/revision-v2/ui-check.json')
    assert len(ui['browser'])==2 and all(row['ok'] for row in ui['browser'])
    verification={'ok':True,'new_duels':total,'faults':0,'illegal_actions':0,'timeouts':0,
                  'max_action_ms_both_players':max_action,'max_setup_ms_both_players':max_setup,
                  'frozen_fortress_source_policy_verified':True,'all_conditions_first_pair_reproduced':True,
                  'demo':'replays/fortress-demo.json','demo_winner':result['winner'],
                  'ui_checks_each_viewport':[len(r['checks']) for r in ui['browser']],
                  'legacy_verification':'results/revision-v2/legacy-verification.json'}
    external_rows=read('results/revision-v2/external/champion-native.json')
    for old in external_rows:
        current,_=play(('fortress','champion'),old['seed'],old['first'],'native')
        assert current['winner']==old['winner'] and current['shots']==old['shots']
    verification['fortress_external_equivalence_games']=len(external_rows)
    save_json(ROOT/'results/revision-v2/verification.json',verification)
    text=f'''# 第二轮调整：胜率与交付验证

日期：2026-10-04。目标：提高实际比赛胜率。原版源码及策略保留于 `baselines/v1-source.zip`，原版全部结果保留于 RESULTS.md；本轮没有覆盖它们。

## 推荐运行 Fortress

```powershell
python -m battleship demo --bot fortress --opponent champion --style native --seed 20261005
python -m battleship evaluate --bot fortress --opponents champion density balanced --pairs 300 --seed-start 1620000 --styles native --workers 8 --out results/reproduced-fortress
python -m battleship protocol --bot fortress
```

Fortress 保留原 Champion 的攻击算法，改变部署：从 64 套新生成的随机布局中，用标准、偏边缘、温和边缘三种不同攻击器模拟，按最差攻击器生存发数与平均发数的组合评分，从前两套中随机选择。它只查看自己拟部署的舰队，不读取真实对手隐藏状态。

原版部署主要针对标准 Density，容易形成可被边缘优先策略利用的偏好。新版加入不同搜索偏好并提高候选数，目标是让布局对多种攻击器都更难。计算量上升：旧版12套候选，新版64套；所有比赛仍使用相同5秒初始化、1秒单步预算。

## 冻结后的独立原生部署比赛

{table(fortress['results'])}

每项300个独立种子 `1620000..1620299`，各跑先后手，完全未用于候选选择。两方都使用自己的部署策略。Bootstrap 按种子组重采样4,000次，避免把两个先后手当作独立样本。

这证明的是本地规则、给定对手、允许自行部署且预算充足条件下的表现，不是官方比赛获胜证明，也不是攻击算法本身的提升。新旧攻击算法相同；固定外部棋盘时不应把部署改进当成攻击改进。

## 未作为主升级版的 Balanced

Balanced 减弱固定边缘偏好、短舰偏好，并取消追击时的边缘修正。它仍保留为对照，但原生部署对旧 Champion 的点估计仅44%，因此没有用它替换原 Champion 或把它宣传成全面更强。

{table(native['results'])}

四种固定部署下的全部结果：

{table(balanced['results'])}

该探索的开发种子60000..60159，验证70000..70399；最终固定部署1600000..1600399、原生部署1610000..1610299。后续 Fortress 使用独立的85000..85199部署验证以及1620000段最终种子；没有利用上述最终棋盘训练布局。

## 部署开发验证

在85000..85199的200套独立验证中，筛选所用随机攻击流与验证攻击流分离。旧部署被Champion击沉平均45.80发，robust 12/32/64候选分别48.805/51.06/51.195发。64候选对Density与Balanced分别53.275/51.18发，按最差验证攻击器表现选出，冻结后才进行上面的最终比赛。

这些是单人清盘发数，不等于对战胜率。64套候选较32套的Champion发数提升很小，选64是依据三个验证攻击器中最差表现，代价是更长的部署时间。较严格初始化预算可用 `policies/defense-v2/trial-2.json` 的32候选版本，未为该版本另外宣称最终胜率。

## 验证与范围

- 本轮最终对战合计 **{total:,} 局**，非法动作、超时、其它Bot异常均为0。每个条件的第一对先后手已重新执行并核对胜负/发数/回放。
- 最慢实测行动 **{max_action:.2f} ms**，初始化/部署 **{max_setup:.2f} ms**。Windows、Python3.14.7、Core Ultra7 255HX；最终Fortress使用8个单线程比赛进程，不使用GPU。
- 单元与集成测试包含公开信息隔离、robust部署重复性、序列化重载、终局和外部进程超时。测试准确数量以本轮 tests.txt 与 DELIVERY.json 为准。
- 原版13,220局统计没有修改；冻结源码哈希和策略哈希通过校验，原版每个条件的前两个种子组及20局外部接口等价性也已复跑。
- 新Fortress额外完成10局真实JSONL子进程对战，硬初始化预算5秒，0错误/超时；10局全部与同种子进程内实现的胜负及发数一致。这只是接口验证，不用这个小样本宣称实力。
- 界面修复：刷新恢复对局及对手；回放战报/发数随进度更新；保存当前显示的导入回放。桌面和窄窗口各28项真实DOM检查通过。原回放不含逐步耗时，因此回放时清除旧对局耗时，退出后恢复。
- `ContextBot` 是另一个公开反馈空间模型实验，仅完成小规模smoke和正确性测试。并行研究触及平台用量限制后停止扩大该实验，没有宣称它提升胜率或加入默认比赛入口。

## 文档与复现

`experiments/defense_v2.py` 可复跑部署候选选择，`experiments/refine_v2.py` 与 `refine_v2_target.py` 复跑Balanced开发。`experiments/ui_check_v2.py` 运行浏览器回归；`experiments/revision_report.py` 核对本轮保存结果并复跑每项首对种子。后续重新训练会改变策略文件，请先复制冻结策略。

只按新功能需要更新了当前源码；不要把新源码哈希当作旧报告的源码哈希。旧报告由 `baselines/v1-source.zip` 认证，旧版完整动作仍与当前兼容路径一致。
'''
    (ROOT/'REVISION_V2.md').write_text(text,encoding='utf-8')
    print(json.dumps(verification,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
