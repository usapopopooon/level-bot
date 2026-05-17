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

`/stats *` と `/ping` `/info` は **Administrator 権限のみ** デフォルトで使用可。
`/level` は誰でも使え、結果は実行チャンネルにそのまま表示される (パブリック)。

#### 一般ユーザー向け

| Slash command | 説明 |
| --- | --- |
| `/level` | 自分の総合レベル・進捗バー・累計 XP を表示 |

#### 管理者専用

| Slash command | 説明 |
| --- | --- |
| `/stats server [days]` | サーバーの直近 N 日合計サマリ (メッセージ / ボイス / リアクション 受送) |
| `/stats profile [user] [days]` | 自分または指定ユーザーのプロフィール |
| `/stats level [user]` | 指定ユーザーの総合 + 項目別レベル (lifetime 累積) |
| `/stats leaderboard [metric] [days] [limit]` | ユーザーランキング (messages / voice / reactions_received / reactions_given) |
| `/stats channels [metric] [days] [limit]` | チャンネル別ランキング |
| `/stats exclude add/remove/list` | 集計対象チャンネルの除外管理 |
| `/stats exclude-user add/remove/list` | 表示から除外するユーザーの管理 (集計データは保持) |
| `/ping` | Bot レイテンシ |
| `/info` | サーバー登録情報 |

### 集計項目

- **メッセージ**: 件数、文字数、添付数
- **ボイス**: 滞在秒数 (進行中セッションも live 反映)
- **リアクション**: 受領数 / 送付数。1 メッセージ × 1 リアクター = 1 加算 (絵文字違いで重複しない)。reactor または message author が bot のものは `count_bots=False` で除外。セルフリアクションは常に除外
- **レベル**: 上記 XP の合計 + 項目別。VC は常に `1 XP/分`、TC/リアクションは「重みログ」の有効日で切替
  - 初期重み (1970-01-01 から): TC `2/件` · リアクション `0.5/個`
  - 現行重み (2026-05-17 から): TC `30/件` · リアクション `20/個`
  - 重み変更は過去分を再計算せず、**有効日以降の獲得分にのみ適用**
  - 曲線は `req(L) = 100 × 1.2^(L-1)`、期間減衰なし
- **レベル到達ロール付与**: 総合レベルが指定値以上になったユーザーへロールを自動付与
  - 設定は **Web 管理画面のみ** で変更可能
  - UI はロール表示名で選択 (ドロップダウン + 入力サジェスト)
  - 内部保存は `role_id` で行い、同名ロールが複数あっても区別可能

### Web ダッシュボード (ログイン必須)

`ADMIN_USER` / `ADMIN_PASSWORD` でログインする単一管理者方式 (httpOnly JWT クッキー)。
未認証アクセスは `/login` へリダイレクト。

- `/login` — 管理者ログイン
- `/` — Bot を導入しているサーバーの一覧
- `/g/[guildId]` — サーバーダッシュボード
  - StatCard: メッセージ / ボイス / リアクション (受 / 送) / アクティブユーザー
  - 日別アクティビティ (Recharts AreaChart)
  - ユーザー / チャンネルランキング (各 metric)
  - レベルランキング (axis 別)
  - レベル到達ロール付与ルールの管理 (Lv N → 任意ロール)
- `/g/[guildId]/u/[userId]` — ユーザープロフィール
  - 累計とランク、項目別レベル、日別バーチャート、主要発言チャンネル

### 管理画面 API (cookie 認証)

管理画面から利用する設定系 API:

- `GET /api/v1/guilds/{guild_id}/roles`
  - 候補ロール一覧 (managed / `@everyone` は除外)
- `GET /api/v1/guilds/{guild_id}/level-role-awards`
  - 現在のレベル到達ロール付与ルール
- `PUT /api/v1/guilds/{guild_id}/level-role-awards`
  - ルール全置換 (`rules: [{ level, role_id }]`)
  - `level` は `0` 以上の整数 (`0` も指定可能)
- `GET /api/v1/leveling/xp-weight-logs`
  - XP 重みの履歴一覧を取得 (有効日昇順)
- `POST /api/v1/leveling/xp-weight-logs`
  - 新しい重みを追加 (`effective_from` は最新ログより未来日が必要)
- `POST /api/v1/leveling/xp-weight-logs/rollback`
  - 「ひとつ前の重み」を新しい `effective_from` で再適用 (履歴として追加)

`Authorization: Bearer <EXTERNAL_API_KEY>` を使う外部 API では
`PUT` は使用不可 (`405`)。設定変更は管理者ログイン (session cookie) が必要。

### 外部 API (server-to-server)

別アプリから Bearer トークンで叩く読み取り専用 API。詳細は
[docs/external-api.md](docs/external-api.md) を参照。

```bash
curl -H "Authorization: Bearer $EXTERNAL_API_KEY" \
  https://level-bot-host/api/v1/guilds/123/levels/leaderboard
```

- 認証: `Authorization: Bearer <EXTERNAL_API_KEY>`
- メソッド: **GET のみ** (POST 等は 405)
- レート制限: 失敗 10 回 / 60 秒で 429

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

### 推奨構成 (4 サービス)

| Service | Source | Builder | Custom Start Command |
| --- | --- | --- | --- |
| `db` | Railway Postgres plugin | — | — |
| `bot` | repo root | Dockerfile (root) | `python -m src.main` |
| `api` | repo root | Dockerfile (root) | `python -m src.web` |
| `frontend` | Service Root を `frontend/` に設定 | Dockerfile (`frontend/Dockerfile`) | (Dockerfile デフォルト) |

`bot` と `api` は同じ Docker イメージを使い、Custom Start Command でロールを切り分ける。
alembic マイグレーションはどちらの起動コードからも自動で走る (`src/migrations.py`)。

代替: shell スクリプト経由で起動したい場合は [scripts/start-bot.sh](scripts/start-bot.sh) /
[scripts/start-api.sh](scripts/start-api.sh) を使える (Heroku Procfile 互換)。
1 コンテナで bot+api を同居させたい場合 (PoC など) は Custom Start Command を空にすれば
Dockerfile デフォルトの [scripts/start-all.sh](scripts/start-all.sh) が走る。

### 必須環境変数

`bot+api` サービス:

- `DISCORD_TOKEN` — Discord Bot Token
- `DATABASE_URL` — Postgres 接続 URL (Railway Postgres プラグインから自動)
- `DATABASE_REQUIRE_SSL=true` — Railway Postgres は SSL 必須
- `CORS_ORIGINS` — フロントの URL (例: `https://level-bot-frontend.up.railway.app`)
- `ADMIN_USER` / `ADMIN_PASSWORD` — 管理画面ログインの資格情報
- `SESSION_SECRET_KEY` — JWT 署名鍵 (`openssl rand -hex 32` で生成、本番必須)
- `SECURE_COOKIE=true` — HTTPS 環境ではセキュアクッキー有効化
- `EXTERNAL_API_KEY` — 外部 API キー (server-to-server 用、未設定で機能無効)
- `ENVIRONMENT=production` — 本番として上記必須 env の検証を有効化
- `TIMEZONE_OFFSET=9` (任意)
- `PORT` — Railway が自動で注入

`frontend` サービス:

- `API_URL` — `bot+api` の URL (Railway 内部 URL 推奨)
- `PORT=3000`

すべての env と説明は [.env.example](.env.example) を参照。

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
