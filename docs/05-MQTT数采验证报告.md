# 05 · M2 续：MQTT 设备数据采集验证报告

> 目标：让项目真的能「采设备数据」——这是 JD 加分项 3 点名、而简历原本完全没有的能力。
> 结论：**采集器 + 模拟器跑通，实时数据落库并被 Agent 真实使用；77 个后端测试通过。**

---

## 1. 架构选择：采集器是独立进程，不是 API 的后台任务

```
模拟 PLC ──publish──▶ mosquitto ──subscribe──▶ collector ──▶ Postgres ──▶ Agent 工具
line/<station>/telemetry
```

理由有两条，都是工程性的：

1. **真实产线里采集器跑在边缘、贴着设备**，应用只读它落库的结果。把它塞进 API 进程会让部署拓扑说谎。
2. **broker 挂了不该把 API 一起拖死**。采集是可用性问题，推理是业务问题，两者的失败半径应该分开。

在 compose 里它用 profile 隔离：

```powershell
docker compose up -d --build                  # 确定性 demo（默认）
docker compose --profile live up -d --build   # 加上实时数采
```

**默认 demo 仍然完全确定**——同样的种子数据、同样的脚本化模型、每次跑出同样的数字。要看不那么"干净"的实时数据，才需要显式打开 profile。

## 2. 线格式（wire contract）

主题：`line/<station>/telemetry`，载荷：

```json
{"metric": "vibrationMm", "value": 0.1934, "baseline": 0.06, "recordedAt": "...", "source": "simulated"}
```

三个刻意的决定：

- **基线走在报文里**，不是事后查表。读数离开它该对比的基准就没有意义，而设备自己最清楚自己的设定值；
- **没有时间戳就用采集器的时钟补上**，而不是假装有；补出来的时间会如实写进库；
- **解析是一个纯函数** `parse_message(topic, payload)`，所以「非法报文怎么办」这件事只在一个地方决定，可以穷举测试，而不是散落在 MQTT 回调里。

## 3. 验证证据

| 项 | 结果 |
|---|---|
| 后端测试 | ✅ **77 passed** |
| ruff / ruff format / **mypy --strict** | ✅ 41 个源文件无问题 |
| compose 配置（默认 + live） | ✅ 两者 `config --quiet` 均通过 |
| 采集器连接与订阅 | ✅ `collector started against mosquitto:1883` / `subscribed to line/+/telemetry` |
| 落库 | ✅ 60 秒内 **48 行 `source='mqtt'`**（对照 144 行 `simulated`） |
| **实时数据进入 Agent 推理** | ✅ 见下 |

最有分量的一条：一次**经 nginx 的真实运行**，遥测工具读的是实时入库的读数，而不是种子数据：

```
query_defects      ok=true  (source: simulated dataset — not real production data)
query_telemetry    ok=true  (source: mqtt)
  temperatureC: 71.9862 vs baseline 68 (1.06x)
  vibrationMm: 0.1934 vs baseline 0.06 (3.22x)  <-- deviation
  beltSpeed: 0.9926 vs baseline 1 (0.99x)
find_similar_cases ok=true  → WO-20260901-001（历史同失效模式）
create_work_order  ok=true  → WO-20261014-001，linked run: run-895ffda9d453
```

`3.22x` 这个数字是从**实时采到的** 0.1934 算出来的，不是种子库里写死的 0.199。整条「设备 → 采集 → 库 → Agent → 工单」的链路是通的。

## 4. 本轮抓到的三个问题

### 4.1 asyncpg 跨事件循环

```
RuntimeError: got Future attached to a different loop
```

应用的 engine 是在 TestClient 的循环里建的，而异步测试跑在 pytest 自己的循环里，`sessionmaker_for` 的全局缓存把它们串到了一起。

修法不是去改缓存，而是**让需要特定循环的测试自己持有 engine**（`session_factory` 夹具，`NullPool`，测试结束即 dispose）。这是 asyncpg 的固有限制，不是可以绕过的实现细节。

### 4.2 测试把数据写进了 demo 库

我发现一台实时运行里出现了 `封装 / vibrationMm / 0.21 / baseline 0.04` 这样一行——**那是我自己的测试残留**。测试与 demo 共用同一个数据库，而 `flush()` 一律写 `source='mqtt'`，于是测试数据伪装成了生产采集数据。

修法：测试夹具在会话结束时**把库还原**（再跑一次 `bootstrap --reset`）。验证过了——测试跑完后表里只剩 144 行 `simulated`。

### 4.3 工具把溯源硬编码了

遥测工具原先把 `(source: simulated dataset — not real production data)` 写死。接入实时采集之后，这句话**变成了假话**——它读的已经是 MQTT 数据了。

修法：`TelemetryReading` 增加 `source` 字段，溯源行由**数据本身**推导：

```
sources = sorted({reading.source for reading in readings})
```

并补了一条测试：用一个只返回 `mqtt` 数据的假件，断言输出里出现 `(source: mqtt)` 且**不出现** `simulated`。

同理，脚本化的 demo 答案里原来写着「数据来源：simulated 数据集」，也改成了「数据来源：各步骤的工具观测中标注的 source 字段」——脚本化的 provider 读不到自己的观测，就不该声称数据来源。

## 5. 验证边界

**未做**：

- **采集器没有背压与持久化缓冲**。队列满时丢弃并计数（`rejected`），进程重启期间的消息依赖 broker 的 QoS 1 重投，没有落盘的 WAL；
- **没有断线重连的显式策略**，依赖 paho 的默认行为；
- **`find_similar_cases` 仍是词法匹配**，向量召回未做；
- **前端还没消费实时数据**——`source` 已经能从 API 看到，UI 尚未展示。

这些都不是「已完成」的一部分，写在这里是为了让边界清楚。
