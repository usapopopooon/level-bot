"""Activity tracking (write-side) feature.

Discord イベント (メッセージ送信・ボイス入退室) を ``daily_stats`` に
集計する書き込み側。読み出し系 (summary / ranking / profile) はそれぞれの
feature に分かれている。

ボイスは「進行中」を ``voice_sessions`` に保持し、退室時 / Bot 再起動時
flush に ``daily_stats`` へ書き込む 2 段構成。日付境界 (ローカル TZ)
分割もここに含まれる。
"""
