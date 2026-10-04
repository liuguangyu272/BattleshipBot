"""Generate the Chinese report from saved measurements, not hand-entered scores."""
from pathlib import Path
import json
import statistics
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from battleship.arena import wilson

ROOT=Path(__file__).resolve().parents[1]


def read(path):
    return json.loads((ROOT/path).read_text(encoding='utf-8'))


def percent(value):
    return f'{value*100:.2f}%'


def table(entries):
    lines=['| 对手 | 部署条件 | 对局 / 独立种子 | 胜率 | 95% 区间 | 先手 / 后手胜率 |',
           '|---|---|---:|---:|---:|---:|']
    for r in entries:
        ci=r['paired_bootstrap_95ci']
        mark=''
        if r['wins'] in (0,r['games']):
            ci=wilson(r['independent_seeds'] if r['wins'] else 0,r['independent_seeds'])
            mark='†'
        lines.append(f"| {Path(r['opponent']).name} | {r['style']} | {r['games']} / {r['independent_seeds']} | {percent(r['win_rate'])} | {percent(ci[0])}–{percent(ci[1])}{mark} | {percent(r['first_win_rate'])} / {percent(r['second_win_rate'])} |")
    return '\n'.join(lines)


def main():
    main=read('results/final-main/summary.json')
    stress=read('results/final-stress/summary.json')
    defense=read('results/final-defense/summary.json')
    strong=read('results/final-strong-defense/summary.json')
    external=read('results/final-external/summary.json')
    verified=read('results/delivery-verification.json')
    ablation=read('results/final-ablation/results.json')
    compare=read('results/final-ablation/comparisons.json')
    ablation_table=['| 策略 | 平均击沉发数（越低越好） | uniform | edge | cluster | spread |',
                    '|---|---:|---:|---:|---:|---:|']
    for row in ablation:
        means=[statistics.mean(r['shots'] for r in row['rows'] if r['style']==s) for s in ['uniform','edge','cluster','spread']]
        ablation_table.append(f"| {row['name']} | {row['mean_shots']:.3f} | "+' | '.join(f'{m:.3f}' for m in means)+' |')
    text=f'''# 实测结果与复现报告

日期：2026-10-04（Asia/Shanghai）。状态：本地评估通过，**没有官方比赛或其他未测试模型的胜利证明**。

## 结论

最终交付的 Champion 在双方自主部署的 1,000 局/对手测试中，对 Density 胜率 **67.20%**，对 Hunt **68.30%**，对初版 Admiral **62.20%**，对随机策略 **100%**。使用同样部署优化的更强 Density 对手，600 局胜率 **67.83%**。

优势并非在每种条件成立：统一均匀部署时，对 Density 只有 **46.20%**，对初版 Admiral **45.30%**。四种分布平均击沉效率有所提升，但主要收益来自 edge 分布；uniform 与 cluster 有退步。不能称为普遍最优策略。

## 主比赛

{table(main['results'])}

每项 500 个独立种子 `900000..900499`，每种子交换先后手。uniform 使用裁判生成的均匀合法舰队，隔离攻击策略；native 使用各 Bot 自己的部署，包含部署策略效果。Random、Hunt、Density 原生均匀部署，初版 Admiral 使用混合部署，Champion 使用混合候选筛选。

95% 区间按独立种子整组 bootstrap 4,000 次，不把一对先后手对局当作两个独立样本。† 全胜时普通 bootstrap 退化为 100–100，本报告改用 500 个种子组的 Wilson 边界区间；原始 JSON 如实保留原 bootstrap 字段。置信区间按条件单独计算，未做多重比较校正。观察到全胜不意味着真实胜率必为 100%。

## 部署压力测试

{table(stress['results'])}

每项 200 个新种子 `910000..910199`，交换先后手；双方采用同一种偏置部署，避免通过只给一方更难的棋盘制造攻击优势。edge 偏边缘，cluster 偏聚集，spread 偏离随机锚点。具体生成分布以 core.py 为准。

cluster 下对 Density 的点估计 44.25%，说明当前边缘与短舰权重不能适应所有部署风格。这里保留全部不利结果。

## 部署消融与更强规则对手

{table(defense['results']+strong['results'])}

`attack-only.json` 与 Champion 的攻击算法、参数相同，区别是关闭 12 候选部署筛选，仍然使用 mixed 部署。测试使用 `930000..930499`，胜率 51.40%，区间跨过 50%，**未证明部署筛选对这个攻击器有稳定收益**。筛选效果对攻击器有依赖，能够修正边缘偏好的对手可以抵消收益。

`defended-density.json` 是基线 Density 加上同样的 12 候选部署筛选，种子 `940000..940299`；它不是只会随机部署的弱对手。Champion 对它测得 67.83%，但也不能据此推断战胜所有概率算法。

## 攻击组件消融

每个策略在完全相同的 2,000 个隐藏棋盘上独立攻击至全部击沉：500 个种子 `920000..920499` × 四种部署。无对手早停，发数可直接比较。

{chr(10).join(ablation_table)}

Champion 相对未优化 Density，平均减少 {-compare[-1]['delta_shots_vs_baseline']:.3f} 发；按种子对四种分布聚合后的配对 bootstrap，差值（Champion−baseline）的 95% 区间为 [{compare[-1]['paired_seed_bootstrap_95ci'][0]:.4f}, {compare[-1]['paired_seed_bootstrap_95ci'][1]:.4f}] 发。

纯参数优化的 tuned_density 在这个最终集合平均 45.508 发，比最终混合版 45.618 发略低。最终测试没有支持“联合采样或残局搜索一定带来额外提升”的说法。Champion 是此前开发验证选择并冻结的版本，未根据最终数据重新挑选；对应的简单版本保留在 `policies/hunt-search/best.json`，可以直接加载。

## 正确性、延迟与进程接口

- 最终双人比赛合计 **{verified['total_final_duels']:,} 局**，非法动作 **0**，超时 **0**，其他 Bot 错误 **0**。攻击消融另有 8,000 次单人完整清盘，不混入比赛局数。
- 两名玩家所有行动中最大实测延迟 **{verified['max_action_ms_both_players']:.2f} ms**；最大初始化/部署 **{verified['max_setup_ms_both_players']:.2f} ms**。本地行动预算 1,000 ms、初始化预算 5,000 ms。
- 硬件 Intel Core Ultra 7 255HX，20 逻辑 CPU，约 16 GB RAM；Windows、Python 3.14.7。每个比赛工作进程只运行一个单线程 Bot；每批 4 workers，部分实验批次同时进行，时间含系统竞争。没有 GPU。
- 19 项 unittest 通过。包括几何与相邻规则、重复动作和越界、轮流规则、胜负、信息副本隔离、小棋盘独立概率穷举核对、策略保存重载、完整对局、进程超时清理。
- 外部 JSONL Champion 与 Density 实际完成 20 局，0 错误/超时；结果为 8 胜 12 负，仅作接口检查，样本不足以判断实力。全部 20 局与同种子的进程内版本胜负和发数一致。
- 每个最终实验条件重新运行前两个种子组并核对结果；保存的源码/策略哈希通过核对；完整演示的全部 94 个事件重新执行后逐一一致。
- 真实浏览器 DOM 检查桌面与窄窗口：人机射击、AI 应答、整局演示、赛后回放、滑动回放、展开规则卡片持续显示均通过。窄窗口实际 viewport 504 px，不宣称真机手机测试。截图和检查日志在 results/。

## 完整演示

`replays/final-demo.json`：seed=20261004，Champion 对 Density，自主部署。**Density 获胜**，双方各射 47 发，共 94 个事件。这个预先指定种子的失败对局如实保留，没有用挑选的胜局替代。

## 复现

在项目根目录运行：

```powershell
python -m unittest discover -s tests -v
python -m battleship demo --bot champion --opponent density --seed 20261004 --style native --out replays/reproduced-demo.json
python -m battleship replay replays/reproduced-demo.json
python experiments/reproduce_final.py
python experiments/final_ablation.py
```

主评估、压力测试、部署消融分别输出到 `results/reproduced/`，不会覆盖原始最终比赛。攻击消融脚本会重写自身 `results/final-ablation/`，如需保留时间原值请先复制。Python 3.14.7 上胜负、动作可复现；延迟无法逐毫秒复现。

完整数据：`results/final-main/`、`final-stress/`、`final-defense/`、`final-strong-defense/`、`final-external/`、`final-ablation/`。每局有种子、先后手、双方发数、获胜方、延迟和错误记录。开发阶段数据位于 `policies/` 各实验子目录，不与最终结果混淆。

## 尚未解决

官方协议、真实比赛对手和正式计算限制尚未提供。当前只支持公开击沉格子的本地规则。均匀和聚集部署仍存在攻击策略退步，部署筛选也没有对所有攻击器显示优势；需要后续独立实验验证自适应部署先验，不能据现有结果声称已经解决。没有跨 Python 版本或另一台机器的性能验证。

未执行关机：缺少用户要求的“其他工作已经保存”确认。任务自身产物均保存，结束本任务服务后交付。
'''
    (ROOT/'RESULTS.md').write_text(text,encoding='utf-8')
    print('Wrote RESULTS.md from saved measurements')


if __name__=='__main__':main()
