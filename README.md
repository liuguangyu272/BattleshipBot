# 深蓝 Fortress · Battleship 实验室

本项目是本地比赛环境与 Bot，**尚无官方比赛协议，不能把本地通过等同于正式比赛获胜**。

## 本轮更新：推荐 Fortress

新增 `fortress`：保留 Champion 的攻击算法，使用三种不同搜索偏好的攻击器筛选64套随机候选部署。独立600局原生部署比赛中，对旧 Champion 胜率 **72.33%**（300个种子、交换先后手，95%区间67.67%–77.00%）。完整条件、其它对手与失败探索见 [REVISION_V2.md](REVISION_V2.md)。旧 `champion` 和全部旧版成绩保留，不覆盖历史记录。

```powershell
python -m battleship demo --bot fortress --opponent champion --style native --seed 20261005
python -m battleship protocol --bot fortress
```

浏览器默认对手为 Fortress。命令行显式加 `--bot fortress` 选择新版；旧命令行默认仍保留 Champion，便于复现旧结果。部署计算量更大，按本地5秒初始化预算验证，不能直接推定满足未提供的正式比赛限制。

同时修复了刷新恢复对局、回放战报随进度更新、下载当前导入回放。另保留 `balanced` 均衡参数实验，但它没有全面超过原 Champion，不作为主要升级版。

## 最快开始

需要 Python 3.11 或以上（实测 3.14.7），无需 pip 或第三方依赖。Windows 可以直接双击 **start.cmd**；或在本目录打开终端：

```powershell
python -m battleship serve
```

浏览器会打开本地人机界面。点击“开始人机对战”，在右侧未知格射击；也可运行 Bot 演示或打开 JSON 回放。

```powershell
python -m battleship demo --seed 42
python -m battleship replay replays/demo.json
python -m unittest discover -s tests -v
python -m battleship evaluate --bot champion --opponents random hunt density admiral --pairs 100 --styles native --workers 4 --out results/my-evaluation
python -m battleship train --trials 16 --boards 100 --workers 4 --out policies/my-search
python -m battleship evaluate --bot policies/my-search/best.json --pairs 100 --workers 4 --out results/my-trained-evaluation
```

`champion` 自动加载已经保存的 `policies/champion.json`。训练是可重复参数优化，无需 GPU；新训练不会覆盖交付策略。短评估的胜率会波动，完整实测与置信区间见 [RESULTS.md](RESULTS.md)。

## 已验证的表现

最终共 **13,220 局**双人比赛，**0 非法动作、0 超时、0 Bot 错误**。主评估每个对手/条件 500 个独立种子，交换先后手，共 1,000 局。

| 对手 | 双方自主部署胜率 | 统一均匀部署胜率 |
|---|---:|---:|
| Random | 100.0% | 100.0% |
| Hunt | 68.3% | 66.1% |
| Density | 67.2% | 46.2% |
| 初版 Admiral | 62.2% | 45.3% |

**没有证明攻击策略在均匀部署下超过 Density。** 自主部署的优势不能混同为所有棋盘上的攻击优势；完整报告保留不利条件和失败演示。对具有同样部署优化的 Density，另有 600 局实测胜率 67.83%。

原版19项自动测试通过；本轮新增测试见 `results/revision-v2/tests.txt` 与 DELIVERY.json。旧版最终演示、所有最终实验条件的部分种子、外部接口与内部实现等价性都已实际重新运行核对。以下原版测量的单步最大43.67ms、初始化/部署最大695.41ms，**不是新Fortress的部署耗时**；新版延迟见 REVISION_V2.md。

## 本地规则假设

- 10×10，长度按顺序为 5/4/3/3/2，允许相邻但不能重叠；只能直线水平或竖直。
- 双方各射一格交替行动，命中不连射，先击沉全部舰船获胜，无平局。
- 反馈为落空、命中或击沉；击沉公开该舰长度和全部格子。
- 已射过的格子不能再次射击。坐标是零起始整数 `row * 10 + col`，界面显示 A1–J10。
- 正式 Bot 只收到自己的舰队、对方攻击记录、自己攻击得到的公开反馈，不收到敌方隐藏舰队、裁判随机种子。
- 默认每步 1000 ms。本地 Python Bot 在返回后检查时间；外部 JSONL 进程有硬超时并终止进程。
- 未提供对手程序、官方资源限制与协议；这些规则和限制仅是清晰可复现的本地约定。

## 策略

Random 随机合法射击；Hunt 使用棋盘格搜寻与连续命中追击；Density 枚举单舰候选位置并做热度统计。
Champion 在追击和残局阶段推断整支舰队的联合布局，约束不重叠、剩余舰长、所有未归属命中。候选组合少时精确枚举，否则使用带重要性权重的采样，并与确定性追击得分混合。搜索阶段采用优化过的短舰与边缘权重；最后一舰候选很少时做期望剩余发数搜索。部署时用多个攻击器评估 12 套新生成舰队，随机选取较难发现的候选。

不使用深度强化学习，因为可直接利用舰船几何与公开反馈进行概率推断。策略参数可保存为 JSON 并重新加载。优化只使用开发与验证种子，最终评估使用独立种子。

算法与近似边界、全部训练阶段、种子划分见 [docs/METHOD.md](docs/METHOD.md)。最终测试没有证明采样与残局组件一定优于简单的调参 Density；该较快版本也保留，可用 `--bot policies/hunt-search/best.json` 加载。

## 接入比赛

```powershell
python -m battleship protocol --bot champion
```

这是持久进程的 JSONL stdin/stdout 接口：`reset`、`place`、`act`，方便其他语言与比赛裁判接入。协议 schema、坐标、超时、示例外部程序配置见 [docs/PROTOCOL.md](docs/PROTOCOL.md)。未提供官方协议，当前并非某个官方比赛的即插即用提交包。

## 完整复现与继续训练

```powershell
python experiments/reproduce_final.py
python experiments/final_ablation.py
python experiments/verify_delivery.py
```

完整最终比赛需几分钟至十几分钟，取决于机器。每局种子、胜负、发数、延迟和错误均保存；完整回放可用界面“打开回放”查看。

若要复跑开发优化，按顺序执行 `python -m battleship train --trials 16 --boards 100 --workers 4 --out policies/search-v1`、`python experiments/refine.py`、`python experiments/constraint.py`、`python experiments/hunt_search.py`、`python experiments/endgame_defense.py`、`python experiments/select_final.py`。最后一步会重写 `policies/champion.json`，请先复制原策略；这些脚本只使用开发种子，不读取最终评估结果。开发早期的源码修复可能让旧探索日志不再逐项一致，说明见 METHOD.md。

## 文件

`battleship/` 环境、Bot、评估、优化、协议、HTTP 服务；`web/` 人机界面；`tests/` 规则与集成测试；`policies/` 策略；`results/` 实测原始数据；`replays/` 赛后完整回放。

所有操作都在本项目内。服务只绑定 `127.0.0.1`，用 Ctrl+C 停止。没有云服务、API key 或付费依赖。

`DELIVERY.json` 记录交付核验；`MANIFEST.json` 保存文件 SHA-256；`docs/PROGRESS.md` 保存开发与额度检查说明。没有确认其他工作均已保存，因此本次未执行关机。

本轮复现检查：`python experiments/revision_report.py`；浏览器回归：`python experiments/ui_check_v2.py`（Windows Edge，无调试端口）。`python experiments/verify_delivery.py` 从 `baselines/v1-source.zip` 校验旧版本哈希，同时核对当前兼容路径仍复现旧版结果。
