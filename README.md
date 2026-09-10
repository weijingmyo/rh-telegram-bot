# RH Telegram Bot — Robinhood 新币预警

持续扫描 **Robinhood Chain**（GMGN chain id: `robinhood`）新创建代币，结合 Dev 钱包推特曝光与历史 ATH，向 Telegram 推送中文 HTML 预警。

## 功能

1. **新币扫描**：通过 GMGN Agent CLI（`npx gmgn-cli market trenches --chain robinhood --type new_creation --raw`）拉取新创建代币，再调用 `token info` 获取 `dev.creator_address`、`dev.ath_token_info` 等。
2. **推特大V**：用 X API v2 recent search 检索包含 Dev 地址的推文；任一作者 `followers_count > 10000` 则告警，标签 `[推特大V]`。
3. **高ATH Dev**：若该 Dev 曾在任意链发射过 ATH 市值 ≥ `$800,000` 的代币，则告警，标签 `[高ATH Dev]`（来源：`token info` 的 `dev.ath_token_info.ath_mc` + `portfolio created-tokens` 全链聚合）。
4. **惯犯黑名单**：按 Twitter 账号与 Dev 地址分别累计告警次数；任一实体达到 **3** 次后永久拉黑，不再告警（SQLite 持久化）。
5. 每条告警附带 GMGN 全链发射历史摘要与 Token/Wallet 链接。
6. 链列表可配置（当前默认仅 `robinhood`）。

## 技术栈

- Python 3.11+ / asyncio / **aiogram 3**
- SQLite（`aiosqlite`）
- GMGN：优先 **CLI 子进程** `npx gmgn-cli ... --raw`（可选 `GMGN_MODE=http`）
- Twitter：X API v2（可替换 `TwitterProvider` 接口）
- 可选健康检查：`GET /health`（aiohttp）

## 快速开始

### 1. 准备密钥

| 变量 | 说明 |
|------|------|
| `TELEGRAM_BOT_TOKEN` | [@BotFather](https://t.me/BotFather) 创建 |
| `TELEGRAM_CHAT_IDS` | 可选，逗号分隔；也可用 `/start` 订阅 |
| `TWITTER_BEARER_TOKEN` | X Developer Portal → App → Bearer Token（推荐） |
| `GMGN_API_KEY` | [GMGN AI](https://gmgn.ai/ai) API Key；也可写入 `~/.config/gmgn/.env` |
| `SCAN_CHAINS` | 默认 `robinhood` |
| `SCAN_INTERVAL_SECONDS` | 默认 `30` |
| `FOLLOWER_THRESHOLD` | 默认 `10000` |
| `ATH_MC_THRESHOLD` | 默认 `800000` |
| `BLACKLIST_ALERT_LIMIT` | 默认 `3` |

复制环境模板：

```bash
cp .env.example .env
# 编辑 .env
```

### 2. Telegram BotFather

1. 打开 Telegram，联系 `@BotFather`
2. `/newbot` 创建机器人，拿到 token 填入 `TELEGRAM_BOT_TOKEN`
3. 把 bot 拉进群（如需群告警），或私聊 bot
4. 发送 `/start` 订阅；或把 chat id 写入 `TELEGRAM_CHAT_IDS`

### 3. Twitter / X

1. 打开 [X Developer Portal](https://developer.x.com/)
2. 创建 Project + App，开通 **Read** 权限
3. 生成 **Bearer Token** → `TWITTER_BEARER_TOKEN`
4. 需要 recent search 权限（Essential/Basic 套餐通常可用；注意 rate limit）

未配置时 bot **仍可启动**，会打 warning 并跳过推特扫描。

### 4. GMGN

```bash
# 本机可选全局安装
npm install -g gmgn-cli
gmgn-cli config --apply <YOUR_GMGN_API_KEY>
```

或仅设置环境变量 `GMGN_API_KEY`（本项目会注入到子进程）。

**调用方式（已实现）**：默认 `GMGN_MODE=cli`，执行例如：

```text
npx --yes gmgn-cli market trenches --chain robinhood --type new_creation --limit 50 --raw
npx --yes gmgn-cli token info --chain robinhood --address <CA> --raw
npx --yes gmgn-cli portfolio created-tokens --chain <chain> --wallet <dev> --order-by token_ath_mc --direction desc --raw
```

HTTP 模式映射同一 OpenAPI：`POST /v1/trenches`、`GET /v1/token/info`、`GET /v1/user/created_tokens`。

### 5. 本地运行

```bash
cd rh-telegram-bot
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
# 需要 Node.js（CLI 模式）
pytest
python -m src
```

健康检查：`curl http://127.0.0.1:8080/health`

### 6. Docker

```bash
docker compose up -d --build
```

数据目录 `./data` 挂载到容器 `/app/data`，持久化 SQLite。

## Bot 命令

| 命令 | 说明 |
|------|------|
| `/start` | 订阅告警并启动扫描 |
| `/stop` | 取消订阅并停止扫描 |
| `/status` | 运行状态 / 阈值 / DB 统计 |
| `/blacklist` | 查看惯犯黑名单 |
| `/dev <address>` | 查询 Dev 全链发射历史 |

## 黑名单规则

- 实体类型：`twitter`（handle，忽略大小写与 `@`）与 `dev`（地址小写）
- 每次成功发出相关告警，对应实体 `alert_count + 1`
- 达到 `BLACKLIST_ALERT_LIMIT`（默认 3）→ `blacklisted=1`，之后永久跳过
- `(chain, token, reason)` 去重，避免同一代币重复刷屏
- 启动时 bootstrap：把当前 trenches 列表标为已见，只告警之后新出现的币

## 告警内容（HTML）

- 原因标签：`[推特大V]` / `[高ATH Dev]`
- 代币 symbol/name/合约、MC/流动性、Launchpad
- GMGN Token + Wallet 链接
- 推文链接 / 历史 ATH 代币列表
- 全链发射历史摘要
- 惯犯进度：如 `Dev 2/3`

## 7×24 云部署

### Railway（一键 / Docker）

仓库已含 `railway.toml`（Dockerfile 构建 + `/health` 检查）。

1. 在 [Railway](https://railway.app) 连接本仓库（New Project → Deploy from GitHub）
2. 设置环境变量：`TELEGRAM_BOT_TOKEN`、`TWITTER_BEARER_TOKEN`、`GMGN_API_KEY`、`SCAN_CHAINS=robinhood`（其余见 `.env.example`）
3. 添加 **Volume**，挂载到 `/app/data`（持久化 SQLite）
4. 部署后确认 Healthcheck：`/health`，端口 `8080`

### Render

1. Web Service + Docker
2. Disk（persistent）挂载 `/app/data`
3. 配置环境变量
4. Health Check：`/health`

### Fly.io

```bash
fly launch
fly volumes create rh_data --size 1
# fly.toml 中 mount /app/data
fly secrets set TELEGRAM_BOT_TOKEN=... TWITTER_BEARER_TOKEN=... GMGN_API_KEY=...
fly deploy
```

**务必**为 `data/` 使用持久卷，否则重启会丢失黑名单与已见代币。

## 项目结构

```text
src/
  config/     配置
  storage/    SQLite
  gmgn/       GMGN CLI/HTTP 客户端
  twitter/    X API + Provider 接口
  blacklist/  惯犯逻辑
  alerts/     中文 HTML 格式化与发送
  scanner/    扫描管线
  bot/        aiogram 命令
  health.py   /health
  main.py     入口
tests/        单元测试
```

## 开发

```bash
pip install -e ".[dev]"
pytest -q
```

## 许可证

MIT
