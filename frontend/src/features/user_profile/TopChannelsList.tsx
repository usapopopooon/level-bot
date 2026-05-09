import { formatNumber } from '@/shared/format'

import type { TopChannel } from './types'

interface Props {
  entries: TopChannel[]
  title: string
}

/**
 * プロフィールの「主な発言チャンネル」リスト (上位 5 件想定)。
 * ranking 側の ChannelLeaderboardCard と見た目は近いが、user_profile を
 * ranking から切り離すために独立コンポーネントとして持つ。
 */
export function TopChannelsList({ entries, title }: Props) {
  return (
    <div className="rounded-xl border border-white/10 bg-white/5 p-4">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-lg font-semibold">{title}</h2>
        <span className="text-xs text-white/40">メッセージ数</span>
      </div>
      {entries.length === 0 ? (
        <p className="text-sm text-white/50">データがありません。</p>
      ) : (
        <ol className="space-y-2">
          {entries.map((e, idx) => (
            <li key={e.channel_id} className="flex items-center gap-3">
              <span className="w-6 text-right text-sm text-white/40">
                #{idx + 1}
              </span>
              <span className="flex-1 truncate text-sm">#{e.name}</span>
              <span className="text-sm font-medium tabular-nums">
                {formatNumber(e.message_count)}
              </span>
            </li>
          ))}
        </ol>
      )}
    </div>
  )
}
