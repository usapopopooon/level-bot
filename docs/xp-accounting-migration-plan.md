# XP会計モデル移行指示書

## 目的

XP計算を会計的に扱えるようにする。

- 帳簿: 実際に起きた活動ログ。原則として事実を表し、XP都合では書き換えない。
- 為替: 活動量をXPへ換算するレート。日付やスコープごとに評価へ使う。
- 変更ログ: 誰が、いつ、なぜ、どの為替を変更したかを監査できる履歴。
- 評価結果: 帳簿と為替を使って算出したXP/レベル。必要に応じて再計算またはスナップショット化する。

この文書では、デプロイしやすい順に小さく分けて進める。

## 現状の前提

- `daily_stats` は日別・ユーザー別・チャンネル別の活動帳簿として使われている。
- `level_xp_weight_logs` は `effective_from` ごとのXP換算レートとして使われている。
- レベル表示は基本的に `daily_stats` を読み、`level_xp_weight_logs` の該当レートで都度XP換算する。
- 既存の課題は、為替の変更履歴と監査情報が十分に残らないこと。

## 原則

1. 帳簿をXP変更のために直接書き換えない。
2. 為替変更は可能な限りappend-onlyで残す。
3. 取消や訂正は「消す」のではなく、取消レコードまたは新revisionで表現する。
4. 本番の読み取り経路を変える前に、回帰テストで現行の期待値を固定する。
5. DBマイグレーションは、できるだけ読み取りロジック変更と分けてデプロイする。

## Phase 1: 回帰テストを厚くする

### 目的

会計モデル移行前に、現在守りたい振る舞いを固定する。

### 追加するテスト

- 過去日Bに為替を追加すると、B以降のXPだけが変わる。
- Bより前のAのXPは変わらない。
- 同じ帳簿に対して、為替だけを変えるとXPが再評価される。
- lifetimeレベル、windowレベル、leaderboardで換算方針が大きくズレない。
- `total.xp` が各axis XPの合計と一致する。
- 為替変更後も表示除外ユーザーの扱いが変わらない。
- レート変更だけではDiscord通知やロール付与が即時に暴発しない。
- ロール再同期が必要な場合は、明示的な同期要求だけで動く。

### デプロイ

コード挙動を変えないテスト追加なので、本番デプロイは不要。
CIで安定して通ることを確認してから次へ進む。

## Phase 2: 監査ログテーブルを追加する

### 目的

既存の読み取り処理を変えず、変更ログを置ける器だけを先に作る。

### DB案

新規テーブル例: `level_xp_weight_change_logs`

推奨カラム:

- `id`
- `change_id` または UUID
- `effective_from`
- `operation`
- `previous_message_weight`
- `previous_reaction_received_weight`
- `previous_reaction_given_weight`
- `new_message_weight`
- `new_reaction_received_weight`
- `new_reaction_given_weight`
- `actor_id`
- `reason`
- `created_at`

将来サーバー別レートを考えるなら、最初から `guild_id nullable` を追加する。
全体共通レートは `guild_id IS NULL` として扱える。

### マイグレーション方針

- テーブル追加だけにする。
- 既存 `level_xp_weight_logs` の各行を初期change logとしてコピーしてもよい。
- 既存のXP読み取り処理は変更しない。

### デプロイ

DBマイグレーションのみ。
読み取りロジックに触れないため、副作用は比較的小さい。

## Phase 3: 為替変更時に監査ログを書く

### 目的

`level_xp_weight_logs` を更新する前後で、old/newを変更ログへ残す。

### 実装方針

- XP重み保存APIに `actor_id` と `reason` を渡せるようにする。
- 既存行がある場合は、更新前の値を `previous_*` に保存する。
- 新規行の場合は、`previous_*` をNULLにする。
- 更新後の値を `new_*` に保存する。
- `level_xp_weight_logs` の更新と `level_xp_weight_change_logs` の挿入は同一transactionで行う。

### テスト

- 新規為替追加でchange logが1件作られる。
- 既存為替更新でprevious/newの両方が残る。
- エラー時に為替表だけ更新され、change logが残らない状態にならない。

### デプロイ

アプリコードとDBの両方を使うため、Phase 2のマイグレーションが本番適用済みであることを確認してから行う。

## Phase 4: rollbackを会計的な取消に変える

### 目的

「最新から一つ前に戻す」ではなく、「どの変更を取り消すか」を明示する。

### 実装方針

- rollback APIは `change_id` または `target_effective_from` を受け取る。
- 取消対象のchange logを特定する。
- 取消も新しいchange logとして残す。
- 既存の為替表には、取消後の有効値を反映する。

### テスト

- 任意過去日の変更だけを取り消せる。
- 別日の為替には影響しない。
- 取消操作自体が監査ログに残る。
- 同じ変更の二重取消を拒否する、または冪等に扱う。

### デプロイ

互換性のため、旧rollback APIを一時的に残すか、管理画面側と同時に切り替える。

## Phase 5: 為替表のrevision化を検討する

### 目的

`level_xp_weight_logs` の直接上書きをやめ、同じ `effective_from` に複数revisionを持てるようにする。

### DB案

新規または改修テーブル例: `level_xp_weight_versions`

推奨カラム:

- `id`
- `guild_id nullable`
- `effective_from`
- `revision`
- `message_weight`
- `reaction_received_weight`
- `reaction_given_weight`
- `status`
- `created_by`
- `created_at`
- `supersedes_id`
- `change_log_id`

有効な為替は、`effective_from` ごとの最新active revisionとして解釈する。

### 注意

ここからは読み取りロジックが変わるため、Phase 1の回帰テストが重要になる。
必要なら一時的に旧テーブルから新テーブルへ同期し、読み取り切替を別デプロイに分ける。

## Phase 6: サーバー別レートやスナップショットを追加する

### サーバー別レート

必要になったら `guild_id` スコープを導入する。

- `guild_id IS NULL`: 全体デフォルト
- `guild_id = ...`: サーバー固有レート

解決順は、サーバー固有レートがあれば優先し、なければ全体デフォルトを使う。

### 評価スナップショット

ランキングや月次締めのように「その時点の評価結果」を固定したい場合だけ追加する。

候補テーブル:

- `xp_valuation_snapshots`
- `xp_valuation_snapshot_entries`

通常表示は再計算、締め済みレポートはスナップショット、という使い分けにする。

## 推奨デプロイ順

1. Phase 1のテスト追加をmainへ入れる。
2. Phase 2のDBマイグレーションだけをデプロイする。
3. Phase 3の監査ログ書き込みをデプロイする。
4. 運用で変更ログが正しく貯まることを確認する。
5. Phase 4のrollback変更をデプロイする。
6. revision化が必要になった時点でPhase 5へ進む。
7. サーバー別レートや締め処理が必要になったらPhase 6へ進む。

## 実装時のチェックリスト

- 帳簿である `daily_stats` をXP都合で更新していない。
- 為替変更のold/newが監査ログに残る。
- 変更者と理由が残る。
- rollbackや取消も監査ログに残る。
- 読み取り結果のXPとレベルが既存回帰テストと一致する。
- lifetime、window、leaderboardで丸めポリシーが説明可能になっている。
- レート変更で通知やロール付与が予期せず走らない。
