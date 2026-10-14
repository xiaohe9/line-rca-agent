# 03 · M1 收口：Docker / Compose / CI 验证报告

> 目的：把「能部署」从一句话变成可复现的证据，并记录构建过程中真实撞到的坑。
> 结论：**两个镜像都构建成功、四个服务全部起来、经 nginx 的 7 项端到端检查全过。**

---

## 1. 镜像构建

| 镜像 | 结果 | 大小 |
|---|---|---|
| `line-rca-api:dev` | ✅ 构建成功 | 203 MB |
| `line-rca-web:dev` | ✅ 构建成功 | 93.2 MB |

两条安全实践已落地并实测：

| 项 | 实测值 |
|---|---|
| API 容器运行用户 | `app`（UID 10001，非 root） |
| Web 容器运行用户 | UID **101**（`nginx-unprivileged` 镜像，非 root） |
| API 健康检查 | Docker `HEALTHCHECK` 3 秒内转为 `healthy` |

## 2. 编排与端到端验证

`docker compose up -d` 一次拉起四个服务（36 秒）：

```
SERVICE     STATUS                    PORTS
api         Up (healthy)              0.0.0.0:8000->8000/tcp
mosquitto   Up                        0.0.0.0:1883->1883/tcp
postgres    Up (healthy)              0.0.0.0:5432->5432/tcp
web         Up                        0.0.0.0:8080->8080/tcp
```

随后**全部通过 nginx（:8080）**做端到端检查，也就是浏览器实际会走的路径：

| # | 检查 | 结果 |
|---|---|---|
| 1 | `GET /` 返回 SPA 外壳 | ✅ 200 |
| 2 | `GET /assets/index-*.js` 带 `immutable` 缓存头 | ✅ `max-age=31536000, public, immutable` |
| 3 | `GET /some/deep/route` 回落到 SPA 而不是 404 | ✅ 200 |
| 4 | `GET /health` 反代到 API 容器 | ✅ `provider=fake, planner=plan-execute` |
| 5 | `POST /api/analyze/collect` 返回完整轨迹 | ✅ 12 个事件，`run.started → … → run.finished` |
| 6 | 该次运行产出了结论 | ✅ |
| 7 | **`POST /api/analyze` 经 nginx 的 SSE 未被缓冲** | ✅ 12 帧 |

第 7 项是这套编排里最容易出错、也最值得验证的一条：只要漏掉 `proxy_buffering off`，nginx 会把整个流攒到最后一次性吐出来——功能测试仍然会过，但「流式」这个卖点已经死了。

## 3. 构建过程中撞到的两个真实问题

### 3.1 镜像源的同步延迟会打断固定版本的安装

```
ERROR: Could not find a version that satisfies the requirement uv==0.13.1
       (from versions: ..., 0.12.24, 0.13.0)
```

清华镜像当时只同步到 `uv 0.13.0`，而 0.13.1 是前一天才发布的。

**处理**：把 uv 版本也做成构建参数（`ARG UV_VERSION=0.13.1`），并在 Dockerfile 里写明「镜像源滞后时可能需要放宽这个固定版本」。默认走 `pypi.org`，需要国内源时用 `--build-arg PIP_INDEX_URL=…` 注入，而不是把某个镜像硬编码进公开仓库。

### 3.2 分层缓存和包元数据的一次冲突

```
OSError: Readme file does not exist: README.md
hint: `line-rca-api` was included because `line-rca-workspace` (v0.0.0) depends on `line-rca-api`
```

为了缓存依赖层，我先只拷 `pyproject.toml`。但三个 `pyproject.toml` 都声明了 `readme`，而 **uv 即使加了 `--no-install-project` 也会读取包元数据**，于是构建失败。

**处理**：清单层同时拷入三个 README。代价是 README 变更会失效依赖缓存——这个取舍很划算，因为 README 的变更频率远低于代码。

## 4. CI 设计（`.github/workflows/ci.yml`）

六个 job，全部是**在本机已实测通过的命令**：

| Job | 内容 |
|---|---|
| `api` | `uv sync --frozen` → ruff check → ruff format --check → mypy → pytest |
| `kernel-contract` | 单独跑「内核不得引用框架」那条契约测试——它失败应当被读作**架构破坏**，而不是普通测试失败 |
| `web` | npm ci → typecheck → lint → test → build → 体积预算 |
| `images` | 两个 Dockerfile 都能构建（带 GHA 层缓存，不推送） |
| `secrets` | gitleaks 全历史扫描 |
| `compose` | `docker compose config --quiet`，保证编排文件不会悄悄写坏 |

体积预算脚本已本地实测：当前 JS 产物 **138 kB gzip / 预算 300 kB**，超限即红。

> **诚实声明**：CI 工作流**尚未在 GitHub 上真实跑过**——仓库还没推上去。它引用的每条命令都在本机验证过，但 runner 环境、action 版本兼容性属于未验证项。

## 5. 本轮的验证边界

**已验证**：两个镜像构建、四服务编排、七项经 nginx 的端到端检查、非 root 运行、健康检查、体积预算脚本、三个 YAML 的语法与 compose 语义。

**未验证**：GitHub Actions 的真实执行；公网部署（Cloudflare Pages / Tunnel 尚未配置）；Compose 里的 `postgres` 与 `mosquitto` 只是被拉起且健康，**API 还没有连它们**（M2 才接）。
