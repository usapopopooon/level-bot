import { LevelCard } from './LevelCard'
import type { UserLevels } from './types'

interface Props {
  levels: UserLevels
}

/**
 * ユーザープロフィール上の「レベル」セクション。
 * 総合レベルを大きく、項目別 4 つを横並びで表示する。
 */
export function LevelsSection({ levels }: Props) {
  return (
    <section className="space-y-3">
      <h2 className="text-lg font-semibold">レベル</h2>
      <LevelCard label="総合" emoji="⭐" breakdown={levels.total} highlight />
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <LevelCard label="ボイス" emoji="🎙️" breakdown={levels.voice} />
        <LevelCard label="テキスト" emoji="💬" breakdown={levels.text} />
        <LevelCard
          label="リアクション (受)"
          emoji="💖"
          breakdown={levels.reactions_received}
        />
        <LevelCard
          label="リアクション (送)"
          emoji="👍"
          breakdown={levels.reactions_given}
        />
      </div>
      <p className="text-[10px] text-white/40">
        XP 重み: VC 1/分 · TC 2/件 · リアクション 0.5/個。累計 XP で算出 (期間減衰なし)。
      </p>
    </section>
  )
}
