# External API リファレンス

別 Railway プロジェクト等のサーバーから level-bot の集計データを取得するための
読み取り専用 API。FastAPI の `/api/v1/*` を `Authorization: Bearer <key>` で叩く。

ブラウザ向け管理画面と同じエンドポイントを共有しているが、外部からは **GET のみ**
許可される (POST 等は middleware で 405)。`Authorization` ヘッダ無しは admin
クッキー認証パスへ落ちるため、外部利用では必ず Bearer を付ける。

OpenAPI スキーマ (`/docs` / `/redoc` / `/openapi.json`) は **管理者ログイン後のみ**
閲覧可能 (cookie 認証経由)。外部 API キーでは閲覧できない。仕様確認は本ドキュメント
または開発環境の `/docs` を参照。

---

## 1. 認証

### Bearer API キー

```
Authorization: Bearer <EXTERNAL_API_KEY>
```

- `EXTERNAL_API_KEY` は環境変数 (両端で同じ値を共有)
- 推奨生成: `openssl rand -hex 32`
- 空のままだとどんな Bearer ヘッダも `401 Unauthorized`
- 不一致でも `401`
- 認証ヘッダ付きで `GET` 以外を送ると `405 Method Not Allowed`

### エラーレスポンス

| ステータス | 意味                                                         |
|------------|--------------------------------------------------------------|
| 401        | キー未設定 / 不一致 / フォーマット異常                       |
| 404        | リソース不存在 (ギルド未参加 / ユーザー無活動 / 表示除外)    |
| 405        | 外部 API は read-only。GET 以外は拒否                        |
| 422        | クエリパラメータのバリデーション失敗 (FastAPI 既定)          |
| 429        | レート制限 (Bearer 認証失敗を IP 単位で 60 秒 / 10 回でロック) |

```json
{ "detail": "Invalid API key" }
```

### レート制限

- 同一 IP からの **Bearer 認証失敗** が 60 秒間に 10 回を超えると `429`
- 成功リクエストには制限なし (将来追加する可能性あり)
- ロック解除は窓 (60 秒) を経過するまで待つだけ
- 制限は in-memory 実装、Bot プロセス単位 (スケールアウト時は外部 store 検討要)

---

## 2. ベース URL

```
https://<level-bot-host>/api/v1
```

- 別 Railway プロジェクトからは public URL (例: `*.up.railway.app` または独自ドメイン) を使う
- 同一プロジェクト内では `*.railway.internal` 経由も可 (今回想定外)

---

## 3. 共通仕様

| 項目                     | 内容                                                            |
|--------------------------|-----------------------------------------------------------------|
| ID 表現                  | Discord snowflake を **文字列** で扱う (JSON の数値桁数対策)    |
| 日付                     | ISO 8601 (`"2026-05-11"`)。ローカル TZ (デフォ JST) で区切る    |
| ボイス時間               | 秒単位の整数                                                    |
| `days` のレンジ          | 1〜3650 (約 10 年)。デフォルトは 30                             |
| `limit` のレンジ         | 1〜50。デフォルト 10                                            |
| `offset` のレンジ        | 0〜100,000                                                      |
| 表示除外ユーザー         | leaderboard 結果から除外、プロフィール / レベルは 404           |
| 進行中ボイス             | summary / daily / leaderboard では live delta を加算 (一部)     |
| 圧縮                     | レスポンス >= 500 bytes は `gzip` で圧縮 (`Accept-Encoding: gzip` 必須) |
| Cache-Control            | レベル系のみ `private, max-age=30` を付与 (他は no-cache 相当)  |

---

## 4. エンドポイント

### 4.1 `GET /guilds`

公開設定 (`guild_settings.public = true`) のアクティブギルド一覧。

**レスポンス**: `200 OK`, `application/json`

```json
[
  {
    "guild_id": "123456789012345678",
    "name": "My Server",
    "icon_url": "https://cdn.discordapp.com/icons/.../...png",
    "member_count": 256
  }
]
```

---

### 4.1.1 `GET /guilds/{guild_id}/roles`

管理画面向けのロール候補一覧。外部 API キーでも `GET` は取得可能。

**レスポンス**: `200 OK`

```json
[
  {
    "role_id": "123456789012345678",
    "role_name": "Member",
    "position": 10,
    "is_managed": false
  }
]
```

- `managed` ロールと `@everyone` は除外される
- レベルロール付与設定の UI 候補として利用

---

### 4.2 `GET /guilds/{guild_id}/summary`

直近 `days` 日のサマリ。

**パスパラメータ**

| 名前       | 型     | 必須 | 説明                |
|------------|--------|------|---------------------|
| `guild_id` | string | ✓    | Discord guild ID    |

**クエリパラメータ**

| 名前   | 型   | 既定 | 範囲     | 説明                |
|--------|------|------|----------|---------------------|
| `days` | int  | 30   | 1〜3650  | 集計対象日数         |

**レスポンス**: `200 OK`

```json
{
  "guild_id": "123...",
  "name": "My Server",
  "icon_url": "https://...",
  "total_messages": 1234,
  "total_voice_seconds": 567890,
  "total_reactions_received": 42,
  "total_reactions_given": 38,
  "active_users": 17,
  "days": 30
}
```

`404` の条件: ギルドが DB に存在しない / Bot が抜けた後でデータも消えた状態。

---

### 4.3 `GET /guilds/{guild_id}/daily`

日別アクティビティ系列。データの無い日は 0 で埋められる。

**クエリ**: `days` (1〜3650, 既定 30)

**レスポンス**: `200 OK`

```json
[
  {
    "date": "2026-04-12",
    "message_count": 12,
    "voice_seconds": 1800,
    "reactions_received": 3,
    "reactions_given": 1
  },
  ...
]
```

---

### 4.4 `GET /guilds/{guild_id}/leaderboard/users`

ユーザー単位のリーダーボード。表示除外ユーザーは結果から外れる。

**クエリ**

| 名前     | 型     | 既定        | 範囲     | 説明                                              |
|----------|--------|-------------|----------|---------------------------------------------------|
| `days`   | int    | 30          | 1〜3650  | 集計対象日数                                       |
| `limit`  | int    | 10          | 1〜50    | 返す件数                                           |
| `offset` | int    | 0           | 0〜100000| ページング                                         |
| `metric` | enum   | `messages`  | —        | `messages` \| `voice` \| `reactions_received` \| `reactions_given` |

**レスポンス**: `200 OK`

```json
[
  {
    "user_id": "234...",
    "display_name": "Alice",
    "avatar_url": "https://...",
    "message_count": 320,
    "voice_seconds": 18000,
    "reactions_received": 24,
    "reactions_given": 17
  }
]
```

---

### 4.5 `GET /guilds/{guild_id}/leaderboard/channels`

チャンネル単位リーダーボード。引数は 4.4 と同じ (`metric` も同じ 4 値)。

**レスポンス**: `200 OK`

```json
[
  {
    "channel_id": "555...",
    "name": "general",
    "message_count": 800,
    "voice_seconds": 0,
    "reactions_received": 120,
    "reactions_given": 95
  }
]
```

---

### 4.6 `GET /guilds/{guild_id}/users/{user_id}`

1 ユーザーの直近 `days` 日のプロフィール。
表示除外 or データが全く無い場合は `404`。

**クエリ**: `days` (1〜3650, 既定 30)

**レスポンス**: `200 OK`

```json
{
  "user_id": "234...",
  "display_name": "Alice",
  "avatar_url": "https://...",
  "total_messages": 320,
  "total_voice_seconds": 18000,
  "total_reactions_received": 24,
  "total_reactions_given": 17,
  "rank_messages": 3,
  "rank_voice": 7,
  "rank_reactions_received": 5,
  "rank_reactions_given": 9,
  "daily": [
    { "date": "2026-04-12", "message_count": 12, "voice_seconds": 1800,
      "reactions_received": 3, "reactions_given": 1 }
  ],
  "top_channels": [
    { "channel_id": "555...", "name": "general",
      "message_count": 200, "voice_seconds": 0,
      "reactions_received": 15, "reactions_given": 8 }
  ]
}
```

各 `rank_*` は活動 0 のとき `null`。

---

### 4.7 `GET /guilds/{guild_id}/users/{user_id}/levels`

ユーザーのレベル情報 (総合 + 項目別)。

**クエリ**

| 名前   | 型           | 既定   | 範囲    | 説明                                            |
|--------|--------------|--------|---------|-------------------------------------------------|
| `days` | int \| null  | (省略) | 1〜3650 | 省略時は lifetime 累積。指定時は直近 N 日のみ集計 |

**レスポンス**: `200 OK`

```json
{
  "total": {
    "level": 13, "xp": 6760,
    "current_floor": 5181, "next_floor": 6317,
    "progress": 1.0
  },
  "voice": { "level": 10, "xp": 1700, "current_floor": 1556, "next_floor": 1968, "progress": 0.350 },
  "text": { "level": 11, "xp": 2580, "current_floor": 1968, "next_floor": 2462, "progress": 1.0 },
  "reactions_received": { "level": 7, "xp": 540, "current_floor": 471, "next_floor": 671, "progress": 0.345 },
  "reactions_given": { "level": 6, "xp": 340, "current_floor": 309, "next_floor": 471, "progress": 0.191 }
}
```

**レベル算出ルール**

XP 重み:

| 種類                    | 重み                  |
|-------------------------|----------------------|
| ボイス滞在              | 1 XP / 分             |
| テキストメッセージ      | 2 XP / 件             |
| リアクション (受 / 送)  | 0.5 XP / 個           |

レベル曲線:

```
req(L)   = 100 * 1.2^(L-1)              # L レベルに必要な追加 XP
cum(L)   = 100 * (1.2^L - 1) / 0.2      # L 到達に必要な累計 XP
```

総合 XP は 4 axis の整数 XP を合算したもの (axis 別丸めとの整合が取れる)。
**期間による減衰は無し** — 一度上げたレベルは下がらない。

リアクションの重複排除: 同一 `(message, reactor)` に複数絵文字を付けても
daily_stats への加算は 1 回。全絵文字を外せば -1。

**404 条件**: 表示除外ユーザー / 完全に活動ゼロ (lifetime も window も)。

---

### 4.8 `GET /guilds/{guild_id}/levels/leaderboard`

`axis` 指定のレベル降順ランキング。

**クエリ**

| 名前     | 型     | 既定     | 範囲     | 説明                                                                          |
|----------|--------|----------|----------|-------------------------------------------------------------------------------|
| `axis`   | enum   | `total`  | —        | `total` \| `voice` \| `text` \| `reactions_received` \| `reactions_given`     |
| `limit`  | int    | 10       | 1〜50    | 件数                                                                          |
| `offset` | int    | 0        | 0〜100000| ページング                                                                    |

**レスポンス**: `200 OK`

```json
[
  {
    "user_id": "234...",
    "display_name": "Alice",
    "avatar_url": "https://...",
    "level": 12,
    "xp": 4280
  }
]
```

`level` / `xp` は指定 `axis` のもの (lifetime 累積、期間減衰なし)。live ボイスは
計算コスト上スキップしている (個別プロフィールと若干値が違うことがあるが
順位用途では許容)。

---

### 4.9 `GET /guilds/{guild_id}/level-role-awards`

レベル到達時のロール付与ルール一覧。外部 API キーでも `GET` は取得可能。

**レスポンス**: `200 OK`

```json
[
  { "level": 3, "role_id": "123...", "role_name": "Bronze" },
  { "level": 10, "role_id": "456...", "role_name": "Silver" }
]
```

注意:

- `PUT /guilds/{guild_id}/level-role-awards` は管理画面専用の設定 API
- 外部 API キー (Bearer) で `PUT` すると `405 Method Not Allowed`

**パフォーマンス**

- SQL 側で集計 / ORDER BY / LIMIT が完結するため、ギルド内ユーザー数が数千でも
  実用速度 (応答 < 100ms 目安)
- 同点境界では Python 側 (丸めた整数 XP) と SQL 側 (連続値 XP) の順位が 1 つズレる
  ことがある — 順位 #1 / #2 が入れ替わる程度
- レスポンスに `Cache-Control: private, max-age=30` を付与しているので、ブラウザは
  30 秒キャッシュする。サーバー間で叩く側もこの値を尊重するとサーバー負荷を下げられる

---

## 5. クライアント実装例

### Python (httpx)

```python
import os
import httpx

BASE = os.environ["LEVEL_BOT_API_URL"]      # 例: https://level-bot.up.railway.app
KEY  = os.environ["LEVEL_BOT_API_KEY"]      # EXTERNAL_API_KEY と同じ値

def get_top_users(guild_id: str, axis: str = "total", limit: int = 10) -> list[dict]:
    r = httpx.get(
        f"{BASE}/api/v1/guilds/{guild_id}/levels/leaderboard",
        params={"axis": axis, "limit": limit},
        headers={"Authorization": f"Bearer {KEY}"},
        timeout=10.0,
    )
    r.raise_for_status()
    return r.json()
```

### curl

```bash
curl -sf \
  -H "Authorization: Bearer $EXTERNAL_API_KEY" \
  "https://level-bot.up.railway.app/api/v1/guilds/123/summary?days=7" | jq
```

### TypeScript (fetch)

```ts
const res = await fetch(
  `${process.env.LEVEL_BOT_API_URL}/api/v1/guilds/${guildId}/summary?days=7`,
  {
    headers: { Authorization: `Bearer ${process.env.LEVEL_BOT_API_KEY!}` },
  },
)
if (!res.ok) throw new Error(`level-bot ${res.status}`)
const summary = await res.json()
```

---

## 6. 運用メモ

- `EXTERNAL_API_KEY` のローテーションは **両端の env を同時に更新** する
  (一致しないと 401 になるだけなので、ローリングアップグレード時は短時間の失敗を許容)
- レート制限: 認証失敗 10 回 / 60 秒で 429 (成功には制限なし)。叩く側は失敗を
  ログして暴走しないよう注意 (誤キー入力で 429 ロックを起こさない)
- gzip 圧縮対応: `Accept-Encoding: gzip` ヘッダを送るとレスポンスが小さくなる
  (httpx / fetch / requests とも既定で送信)
- レベル系のキャッシュ: ブラウザが `Cache-Control: private, max-age=30` を尊重して
  30 秒キャッシュする。同じ URL を高頻度で叩くなら 30 秒以上の間隔を空ける
- スキーマの後方互換性: フィールド追加のみ。フィールド削除は major bump 扱い
  (現状 v1 のみ)
