# level-bot

[![CI](https://github.com/usapopopooon/level-bot/actions/workflows/ci.yml/badge.svg)](https://github.com/usapopopooon/level-bot/actions/workflows/ci.yml)
[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/downloads/)
[![Next.js](https://img.shields.io/badge/Next.js-16-black.svg)](https://nextjs.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE.md)

Discord サーバー統計 Bot + 公開ダッシュボード。

`../discord-util-bot` の構成 (Python/FastAPI バックエンド + Next.js フロント + 単一の
PostgreSQL + Alembic) を踏襲し、メッセージ・ボイス活動の集計と可視化を提供する。
Railway へのデプロイ前提。

## アーキテクチャ

```
Discord ──▶ Bot (discord.py / src/cogs/stats.py)
                │  upsert
                ▼
            PostgreSQL ──▶ FastAPI (src/web)  ──▶  Next.js (frontend/)
                                                    └─ Recharts でグラフ描画
```

- **Bot プロセス** (`python -m src.main`): メッセージ・ボイスイベントを受け取り
  `daily_stats` に upsert する。
- **API プロセス** (`uvicorn src.web.app:app`): `/api/v1/*` の読み取り専用 JSON API。
- **Frontend** (`frontend/`, Next.js 16 App Router): Server Component から API を fetch
  し、Recharts でグラフを描画する公開ダッシュボード。

## 機能

### Bot

| Slash command | 説明 |
| --- | --- |
| `/stats server [days]` | サーバーの直近 N 日合計サマリ |
| `/stats profile [user] [days]` | 自分または指定ユーザーのプロフィール |
| `/stats leaderboard [metric] [days] [limit]` | ユーザーランキング (messages / voice) |
| `/stats channels [metric] [days] [limit]` | チャンネル別ランキング |
| `/stats exclude add/remove/list` | 集計対象チャンネルの除外管理 (Manage Guild 権限) |
| `/ping` | Bot レイテンシ |
| `/info` | サーバー登録情報 |

### Web ダッシュボード

- `/` — Bot を導入しているサーバーの一覧
- `/g/[guildId]` — サーバーダッシュボード
  - 合計メッセージ・ボイス時間・アクティブユーザー数
  - 日別アクティビティ (Recharts AreaChart)
  - ユーザー / チャンネルランキング (メッセージ・ボイス)
- `/g/[guildId]/u/[userId]` — ユーザープロフィール
  - 累計とランク
  - 日別バーチャート (Recharts BarChart)
  - 主要発言チャンネル

## ローカル開発

```bash
# 1. 依存セットアップ
make install
cd frontend && npm install && cd ..

# 2. .env を準備
cp .env.example .env
# DISCORD_TOKEN を埋める

# 3. Postgres を立てる
docker compose up -d db

# 4. マイグレーション
alembic upgrade head

# 5. 起動 (3 プロセス並行)
make dev      # Bot
make web      # FastAPI (別ターミナル)
cd frontend && npm run dev  # Next.js (別ターミナル)
```

または全部まとめて:

```bash
docker compose up --build
```

- API: <http://localhost:8000>
- Frontend: <http://localhost:3000>
- API docs: <http://localhost:8000/docs>

## Railway デプロイ

Bot + API + Frontend を別サービスとして 1 プロジェクト内にデプロイする想定。

### 推奨構成

| Service | Source | Builder | Start command |
| --- | --- | --- | --- |
| `db` | Railway Postgres plugin | — | — |
| `bot+api` | リポジトリのルート | Dockerfile | `Dockerfile` (デフォルトで bot + uvicorn 並行起動) |
| `frontend` | リポジトリのルート | Dockerfile (`frontend/Dockerfile`) | `node server.js` |

### 必須環境変数

`bot+api` サービス:

- `DISCORD_TOKEN` — Discord Bot Token
- `DATABASE_URL` — Postgres 接続 URL (Railway Postgres プラグインから自動)
- `DATABASE_REQUIRE_SSL=true` — Railway Postgres は SSL 必須
- `CORS_ORIGINS` — フロントの URL (例: `https://level-bot-frontend.up.railway.app`)
- `TIMEZONE_OFFSET=9` (任意)
- `PORT` — Railway が自動で注入

`frontend` サービス:

- `API_URL` — `bot+api` の URL (Railway 内部 URL 推奨)
- `PORT=3000`

### デプロイの流れ

1. Railway プロジェクトを作成し Postgres プラグインを追加
2. `bot+api` サービスを追加 (root を指定 → `railway.toml` が読み込まれる)
3. `frontend` サービスを追加 (root を指定 → `frontend/railway.toml` が読み込まれる)
4. それぞれに環境変数を設定して deploy

`Procfile` も同梱しているので Heroku 形式でも動く。

## テスト

```bash
make test
make lint
make typecheck
```

`pytest` は **Docker daemon が起動していること** を前提にする。
`tests/conftest.py` の session-scoped fixture が
[`testcontainers`](https://github.com/testcontainers/testcontainers-python) で
`postgres:16-alpine` コンテナを 1 つ立て、テストごとに `drop_all → create_all` で
クリーンスキーマにする。本番と同じ Postgres 方言 (`ON CONFLICT DO UPDATE` など)
を使うので、upsert・集計クエリも実環境通りにテストできる。

CI でも GitHub Actions のデフォルト runner なら追加設定不要 (Docker 同梱)。

## ディレクトリ構成

```
.
├── alembic/                      # DB マイグレーション
├── frontend/                     # Next.js + Recharts ダッシュボード
│   ├── src/app/                  # App Router pages
│   ├── src/components/           # Recharts ラッパー含む共通 UI
│   └── src/lib/                  # API fetch & 整形ヘルパ
├── src/
│   ├── bot.py                    # Bot 本体
│   ├── main.py                   # エントリーポイント
│   ├── config.py                 # pydantic-settings
│   ├── constants.py
│   ├── utils.py
│   ├── cogs/                     # 機能 Cog (stats / health / admin)
│   ├── database/                 # SQLAlchemy models + engine
│   ├── services/                 # CRUD + 集計クエリ
│   └── web/                      # FastAPI app + routes
├── tests/                        # ユニットテスト
├── Dockerfile                    # bot + api 用
├── railway.toml                  # bot + api 用
├── frontend/Dockerfile           # Next.js 用
├── frontend/railway.toml         # Next.js 用
├── docker-compose.yml            # ローカル開発用
└── pyproject.toml
```

## ライセンス

MIT
