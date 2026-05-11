# External API リファレンス

別 Railway プロジェクト等のサーバーから level-bot の集計データを取得するための
読み取り専用 API。FastAPI の `/api/v1/*` を `Authorization: Bearer <key>` で叩く。

ブラウザ向け管理画面と同じエンドポイントを共有しているが、外部からは **GET のみ**
許可される (POST 等は middleware で 405)。`Authorization` ヘッダ無しは admin
クッキー認証パスへ落ちるため、外部利用では必ず Bearer を付ける。

OpenAPI スキーマと対話的 UI は `/docs` (Swagger) または `/redoc` で参照可能。

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

```json
{ "detail": "Invalid API key" }
```

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
    "level": 12, "xp": 4280,
    "current_floor": 3540, "next_floor": 4348,
    "progress": 0.915
  },
  "voice": { "level": 8, "xp": 1080, "current_floor": 928, "next_floor": 1213, "progress": 0.534 },
  "text": { "level": 9, "xp": 1640, "current_floor": 1213, "next_floor": 1556, "progress": 1.0 },
  "reactions_received": { "level": 5, "xp": 340, "current_floor": 309, "next_floor": 471, "progress": 0.191 },
  "reactions_given": { "level": 4, "xp": 220, "current_floor": 207, "next_floor": 309, "progress": 0.127 },
  "activity_rate": 0.633,
  "activity_rate_window_days": 30
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

各 axis に直近 30 日のアクティブ率 (`active_days / 30`, 0.0〜1.0) を掛けて減衰。
総合 XP は 4 axis の整数 XP を合算したもの (axis 別丸めとの整合が取れる)。

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
    "xp": 4280,
    "activity_rate": 0.633
  }
]
```

`level` / `xp` は指定 `axis` のもの。live ボイスは計算コスト上スキップしている
(個別プロフィールと若干値が違うことがあるが順位用途では許容)。

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

- `EXTERNAL_API_KEY` をローテーションする際は **両端の env を同時に更新** する
  (一致しないと 401 になるだけなので、ローリングアップグレード時は短時間の失敗を許容)
- レート制限は現状 **未実装**。叩く側で適切な間隔を空ける (例: 30 秒以上)
- スキーマの後方互換性: フィールド追加のみ。フィールド削除は major bump 扱い
  (現状 v1 のみ)
