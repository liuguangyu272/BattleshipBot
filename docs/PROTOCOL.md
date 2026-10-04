# 本地协议 v1 与比赛适配

第二轮 Fortress 沿用同一协议：`python -m battleship protocol --bot fortress`。外部进程示例配置为 `examples/fortress-bot.json`，初始化硬预算5秒，单步1秒。旧 Champion 入口继续保留。

## 官方边界

没有收到官方比赛协议、真实对手、资源限制。本地实现只支持 `local-classic-touching-v1`：允许相邻，命中不连射，击沉公开完整舰格。若正式比赛不公开击沉格子、采用 Salvo 或禁止相邻，需要修改观察与推断器，不能直接宣称兼容。

本地默认行动时限 1000 ms、初始化 5000 ms；标准 Bot 单线程，不需要 GPU。批量实验使用 4 个独立比赛工作进程。Python 内置策略在返回后计时；外部进程通过队列等待实现硬超时并终止。外部进程仅用于受信任本地程序，并非操作系统安全沙箱。

## Python 接口

```python
class Bot:
    def reset(self, rules: dict, seed: int) -> None: ...
    def place(self) -> list[list[int]]: ...
    def act(self, observation: dict) -> int: ...
```

`reset` 清空每局状态并接收**独立的 Bot 私有随机种子**，不是裁判部署种子。`place` 返回按 5/4/3/3/2 顺序的舰船，每舰是一组单元索引。允许自己的部署模拟查看自己候选棋盘，攻击函数不能读取环境对象。

动作 `cell = row * size + column`，行列从零开始。10×10 的 A1=0、A10=9、B1=10、J10=99。动作必须为整数，布尔值、浮点、越界、重复射击均非法。

## 观察

| 字段 | 内容 |
|---|---|
| `rules` | `size`、`fleet`、`rule_id` |
| `grid` | 长度 size²；0 未知、1 落空、2 未击沉命中、3 已击沉 |
| `remaining` | 敌方未击沉舰长，两个 3 分别计数 |
| `sunk` | 已公开的击沉舰格列表 |
| `legal_actions` | 全部尚未射击格子，升序 |
| `shots_taken` | 本方已射击次数 |
| `done` | 是否已击沉全部敌舰 |
| `player`, `to_move`, `winner` | 双人环境附加字段 |
| `own_fleet`, `incoming` | 自己的合法信息；攻击评估不依赖它们 |

单人攻击基准只传前七项，双人比赛增加后两行。`done=true` 时不能调用 `act`。双人对局可能因另一方获胜而结束，裁判负责不再调用任何 `act`。

不包含裁判种子、敌方未公开舰队、占用位图或其他可还原隐藏布局的标识。每次观察复制列表，Bot 修改观察不会改变环境。

## JSONL

从项目根目录启动：

```powershell
python -m battleship protocol --bot champion
```

stdin 每行一个请求，stdout 每行一个响应，必须及时 flush；日志只能写 stderr。同一进程可处理多个 `reset`。

```json
{"v":1,"op":"reset","rules":{"size":10,"fleet":[5,4,3,3,2],"rule_id":"local-classic-touching-v1"},"seed":"12345"}
```

响应：`{"ok":true,"v":1}`。seed 接受十进制字符串或整数，适配器发送字符串，避免 JavaScript 64 位整数精度损失。

```json
{"v":1,"op":"place"}
```

响应：`{"fleet":[[...],[...],[...],[...],[...]]}`，每组实际整数格子；省略号只是文档占位。

```json
{"v":1,"op":"act","observation":{"rules":{},"grid":[],"remaining":[],"sunk":[],"legal_actions":[],"shots_taken":0,"done":false}}
```

上行是结构示意，字段须填入有效观察；响应如 `{"action":44}`。格式错误返回 `{"error":"ValueError","message":"..."}`，不会把日志混入协议。

## 接入另一个程序

复制 `examples/external-bot.json`，把 `argv` 改成实际程序与参数。程序通过参数数组启动，不经过 shell。可以把 `cwd` 改成对手程序目录。

```powershell
python -m battleship evaluate --bot champion --opponents exec:examples/external-bot.json --pairs 20 --styles native --out results/external-check
```

这是本地 JSONL adapter，不是任何未提供的官方协议实现。比赛主办方只需在官方观察与本地 schema 之间编写显式映射；若信息规则不同，必须同时调整模型。

## 回放与判负

回放标注 `REFEREE_FULL_STATE_POSTGAME_ONLY`，包含双方舰队，不能传给正式行动选择。Web 服务在结束前拒绝 `/api/replay`，结束后允许下载。
比赛记录中的 `faults` 保存异常、非法动作、超时及责任方。错误判负，不用随机动作静默替代。弃权对局可能有未结束的棋盘回放，此时比赛获胜方看 `match.winner`，棋盘终局字段仍如实保留为 null。
