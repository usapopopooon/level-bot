# level-bot

[![CI](https://github.com/usapopopooon/level-bot/actions/workflows/ci.yml/badge.svg)](https://github.com/usapopopooon/level-bot/actions/workflows/ci.yml)
[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/downloads/)
[![Next.js](https://img.shields.io/badge/Next.js-16-black.svg)](https://nextjs.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE.md)

Discord サーバー統計 Bot + 公開ダッシュボード。

`../discord-util-bot` の構成 (Python/FastAPI バックエンド + Next.js フロント + 単一の
PostgreSQL + Alembic) を踏襲し、メッセージ・ボイス活動の集計と可視化を提供する。
Railway / Coolify へのデプロイに対応する。

Coolify への移行・運用手順は [docs/coolify.md](docs/coolify.md) を参照。

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
  VC 同席 / リプライ / リアクション相手は `social_edges_daily` に日次集計する。
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
| `/level` | 自分の総合レベル・進捗バー・現在 XP を表示 |

`/level` とレベルアップ通知には、intro-bot 連携が設定されている場合
「チル場所を設定」ボタンが付き、自己紹介に表示するチル場所をその場で変更できる。
カラーロール交換で総合レベルが下がっても設定済みのチル場所は保持し、再設定時は
現在レベルで解放済みの場所だけを選択できる。
`USER_STATS_SITE_*` が設定されている場合は「ユーザー統計を開く」リンクも表示される。

#### カラーロール交換所

管理者が `/color-role add` で交換対象のカラーロールと必要 XP を登録し、`/color-role panel`
で公開パネルを投稿できる。管理画面からも交換対象の追加・無効化と公開パネル投稿を
行える。ユーザーはパネル上のボタンだけで、残高確認、ロール選択、交換確認、
現在のカラーロールの取り外しまで完結する。

レベル計算に使う現在 XP は、獲得・受取 XP から成功済み交換とXPギフトの
送付額・贈与税を差し引いて計算する。
色ロールの切り替え制を前提に、新しい交換ロールを付けると他の交換ロールは外れる。
過去に交換した色へ戻す場合も再度必要 XP を支払う。カラーロールを外しても XP は
戻らない。交換後の返品や XP 払い戻しは行わず、成功済み交換は台帳として残す。
管理画面のパネル投稿は指定チャンネルへ常に新規投稿し、古いパネルの message_id は
保存・参照しない。

`/color-role access-role add|remove|list` で交換所を利用できるロールを管理できる。
複数設定した場合はいずれか1つを持つユーザーとサーバー管理権限を持つユーザーだけが
利用でき、未設定の場合は全員が利用できる。

#### カフェ・コレクション

管理者が `/cafe-gacha setup` を実行すると、カフェカウンター、カフェ台帳、常設パネルを
作成または修復する。`/cafe-gacha access-role add|remove|list` で利用ロールを管理でき、
判定方法はカラーロール交換所と同じ（複数ロールはOR、サーバー管理者は常に利用可能、
未設定なら全員利用可能）。

常設パネルでは1枚引きに加えて最大10枚のまとめ引きを利用できる。まとめ引きは
その時間の残り枠と現在XPに合わせた枚数を1トランザクションで確定し、画像つき結果を
カフェ台帳の1投稿へまとめる。有料になる場合は、本人だけに消費XP・確認後の最低残高・
残り枠を表示して確認を求める。各カードの最低獲得XPは同じまとめ引きの次の1枚にも
使用できる。1時間10回上限は維持するが、日次上限は設けない。
カタログは珈琲・紅茶・日本茶・中国茶、世界の飲み物、喫茶店フードや菓子まで
100種類（飲み物71種・フード29種）あり、
Nは出がらし・代用珈琲・見切り品など、少し残念で親しみやすいネタ枠として扱う。
N/HN/R/SR/SSRの総排出率を変えずに、未収集カードを同一レアリティ内で2倍優遇する。
90種以上の収集後に100回連続でNEWが出なければ、次は未所持カードを確定する。
コレクション棚と排出一覧はレアリティ別に表示し、お気に入り・個別交換も先に
レアリティを選ぶためDiscordの選択肢上限内で操作できる。
初入手カードは結果に収集数の増加を表示し、新規カード名とNEW演出は結果直後の通知へ
まとめる。R・SR・SSRまたは初入手カードが含まれる場合は、カフェ台帳で抽選者を1回
メンションする。レアカードには「SR以上」などその抽選で出た最高レアリティ、初入手には
新規カード名を表示する。
通知対象は抽選した本人のみで、`@here`・`@everyone`・ロールメンションは送信しない。
コレクションの重複交換は「カードを選んで個別交換」と「全カードを一括交換」を
別のボタンで表示し、個別交換では対象カードの1枚・全重複・枚数指定を選べる。

#### XPギフト

管理者が `/xp-gift setup` を実行すると、XPギフトの常設パネルと公開台帳を作成または
修復する。ユーザーはパネルから相手、`1〜3,000 XP` の金額、任意のメッセージを入力し、
本人だけに表示される税額・合計負担・確定後残高と公開メッセージを確認してから贈れる。
メッセージは120文字・4行までで、成功後はギフトカード風のコードブロックとして公開台帳へ
表示する。メッセージなしでも贈れる。同じ送信者から同じ受取人へは
日本時間の日付ごとに1回までで、別の相手へのギフトや逆方向のギフトは別枠として扱う。

1回のギフトごとに最初の1,000 XPは非課税とし、超過分の10%を1 XP単位で切り上げて
送る側から追加徴収する。受取人には指定額をそのまま加算し、税額は消滅する。確定時に
残高と日次枠を再検証し、失敗・キャンセルでは枠を消費しない。成功結果は公開台帳へ
投稿し、実際に通知するメンションは受取人本人だけに限定する。`@here`・`@everyone`・
ロールメンションは送信しない。投稿失敗は最大5回まで自動再試行する。
上限で停止した通知は、管理者が `/xp-gift retry-notifications` を実行した場合にだけ
再開し、再び最大5回の有限回数で試行する。

#### 管理者専用

| Slash command | 説明 |
| --- | --- |
| `/stats server [days]` | サーバーの直近 N 日合計サマリ (メッセージ / ボイス / リアクション 受送) |
| `/stats heatmap [days] [output]` | VC時間帯ヒートマップを画像またはテキストで投稿 |
| `/stats heatmap-daily [enabled] [channel] [time] [timezone]` | 直近7日間のVC時間帯ヒートマップの毎日投稿時刻を設定 / 停止 |
| `/stats profile [user] [days]` | 自分または指定ユーザーのプロフィール |
| `/stats level [user]` | 指定ユーザーの総合 + 項目別レベル (lifetime 累積) |
| `/stats leaderboard [metric] [days] [limit]` | ユーザーランキング (messages / voice / reactions_received / reactions_given) |
| `/stats channels [metric] [days] [limit]` | チャンネル別ランキング |
| `/stats exclude add/remove/list` | 集計対象チャンネルの除外管理 |
| `/stats exclude-user add/remove/list` | 表示から除外するユーザーの管理 (集計データは保持) |
| `/ping` | Bot レイテンシ |
| `/info` | サーバー登録情報 |
| `/color-role add` | カラーロール交換対象を追加 / 更新 |
| `/color-role remove` | カラーロール交換対象を無効化 |
| `/color-role panel` | カラーロール交換所パネルを投稿 |
| `/color-role access-role add/remove/list` | カラーロール交換所の利用ロールを管理 |
| `/cafe-gacha setup` | カフェ・コレクションのチャンネルとパネルを作成 / 修復 |
| `/cafe-gacha access-role add/remove/list` | カフェ・コレクションの利用ロールを管理 |
| `/xp-gift setup` | XPギフトの常設パネルと公開台帳を作成 / 修復 |
| `/xp-gift retry-notifications` | 停止済みを再開して未配信の台帳通知を再試行 |

### 集計項目

- **メッセージ**: 件数、文字数、添付数
- **ボイス**: 滞在秒数 (進行中セッションも live 反映)
- **同一VC人数ボーナス**: 3人以上でティーパーティー1.5倍、5人以上でティーフェスティバル2倍、10人以上でティーカーニバル2.5倍
- **Minecraft×ボイス**: 連携済みユーザーがMinecraftとVCに同時接続中はVC XPを2倍で計算
- **リアクション**: 受領数 / 送付数。1 メッセージ × 1 リアクター = 1 加算 (絵文字違いで重複しない)。reactor または message author が bot のものは `count_bots=False` で除外。セルフリアクションは常に除外
- **レベル**: 総合は獲得・受取 XP から交換消費とXPギフトの送付額・贈与税を差し引いた現在 XP、項目別は各項目の獲得 XP。VC は固定換算、TC/リアクションは「重みログ」の有効日で切替
  - 具体的な重み値は管理画面/APIの現在値を正とする
  - 重み変更は過去分を再計算せず、**有効日以降の獲得分にのみ適用**
  - 曲線は `req(L) = 100 × 1.2^(L-1)`、期間減衰なし
  - まりも復活は `1,000 XP` を消費し、イベントID単位で一度だけ台帳へ記録
  - Minecraftアイテムガチャは通常 `100 XP`、R以上確定 `1,000 XP`。両方を合わせて日本時間の日付ごとに3回まで。配布前に予約し、成功後に確定する。Minecraftが明確に拒否した場合だけ予約を取り消し、成否不明時は二重配布防止のため消費を維持する
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
  - カラーロール交換所の管理 (交換対象ロール / 必要 XP / パネル投稿)
- `/g/[guildId]/u/[userId]` — ユーザープロフィール
  - 累計とランク、項目別レベル、日別バーチャート、主要発言チャンネル

### 管理画面 API (cookie 認証)

管理画面から利用する設定系 API:

- `GET /api/v1/guilds/{guild_id}/roles`
  - 候補ロール一覧 (managed / `@everyone` は除外)
- `GET /api/v1/guilds/{guild_id}/channels`
  - パネル投稿先に使えるテキストチャンネル候補
- `GET /api/v1/guilds/{guild_id}/level-role-awards`
  - 現在のレベル到達ロール付与ルール
- `PUT /api/v1/guilds/{guild_id}/level-role-awards`
  - ルール全置換 (`rules: [{ level, role_id }]`)
  - `level` は `0` 以上の整数 (`0` も指定可能)
- `GET /api/v1/guilds/{guild_id}/color-role-shop/items`
  - 現在有効なカラーロール交換対象
- `PUT /api/v1/guilds/{guild_id}/color-role-shop/items/{role_id}`
  - 交換対象を追加 / 更新 (`role_id`, `cost_xp`, `description`)
- `DELETE /api/v1/guilds/{guild_id}/color-role-shop/items/{role_id}`
  - 交換対象を無効化
- `POST /api/v1/guilds/{guild_id}/color-role-shop/panel`
  - `channel_id` のチャンネルへ交換所パネルを新規投稿
- `GET /api/v1/leveling/xp-weight-logs`
  - XP 重みの履歴一覧を取得 (有効日昇順)
- `POST /api/v1/leveling/xp-weight-logs`
  - 新しい重みを追加 (`effective_from` は最新 version より未来日が必要)
- `POST /api/v1/leveling/xp-weight-logs/rollback`
  - 任意の `target_effective_from` を取り消し、直前の重みを新しい `effective_from` で再適用
- `GET /api/v1/leveling/xp-weight-logs/mirror-check`
  - 正本の XP 重み version と互換用 mirror の整合性を確認

`Authorization: Bearer <EXTERNAL_API_KEY>` を使う外部 API は GET 専用。
`POST` / `PUT` などの変更系は `405` になり、設定変更は管理者ログイン
(session cookie) が必要。

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
- `CHILL_API_KEY` — intro-bot など信頼済みサービスからチル場所を同期するキー。
  未設定なら `EXTERNAL_API_KEY` を流用
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
