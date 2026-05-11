import Link from 'next/link'

import { formatNumber } from '@/shared/format'

import type { LevelAxis, LevelLeaderboardEntry } from './types'

interface Props {
  guildId: string
  entries: LevelLeaderboardEntry[]
  axis: LevelAxis
  title: string
}

const AXIS_LABELS: Record<LevelAxis, string> = {
  total: '総合',
  voice: 'ボイス',
  text: 'テキスト',
  reactions_received: 'リアクション (受)',
  reactions_given: 'リアクション (送)',
}

export function LevelLeaderboardCard({ guildId, entries, axis, title }: Props) {
  return (
    <div className="rounded-xl border border-white/10 bg-white/5 p-4">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-lg font-semibold">{title}</h2>
        <span className="text-xs text-white/40">{AXIS_LABELS[axis]} Lv</span>
      </div>
      {entries.length === 0 ? (
        <p className="text-sm text-white/50">データがありません。</p>
      ) : (
        <ol className="space-y-2">
          {entries.map((e, idx) => (
            <li key={e.user_id} className="flex items-center gap-3">
              <span className="w-6 text-right text-sm text-white/40">
                #{idx + 1}
              </span>
              {e.avatar_url ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  src={e.avatar_url}
                  alt=""
                  className="h-7 w-7 rounded-full bg-white/10"
                />
              ) : (
                <div className="h-7 w-7 rounded-full bg-white/10" />
              )}
              <Link
                href={`/g/${guildId}/u/${e.user_id}`}
                className="flex-1 truncate text-sm hover:underline"
              >
                {e.display_name}
              </Link>
              <span className="text-sm font-medium tabular-nums">
                Lv {e.level}
                <span className="ml-1 text-[10px] text-white/40">
                  ({formatNumber(e.xp)} XP)
                </span>
              </span>
            </li>
          ))}
        </ol>
      )}
    </div>
  )
}
