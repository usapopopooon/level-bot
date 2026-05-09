import Link from 'next/link'

import { formatNumber, formatSeconds } from '@/shared/format'

import type { ChannelLeaderboardEntry, Metric } from './types'

interface Props {
  entries: ChannelLeaderboardEntry[]
  metric: Metric
  title: string
  guildId?: string
  days?: number
}

export function ChannelLeaderboardCard({
  entries,
  metric,
  title,
  guildId,
  days,
}: Props) {
  const moreHref = guildId
    ? `/g/${guildId}/ranking?type=channels&metric=${metric}${
        days ? `&days=${days}` : ''
      }`
    : null
  return (
    <div className="rounded-xl border border-white/10 bg-white/5 p-4">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-lg font-semibold">{title}</h2>
        <span className="text-xs text-white/40">
          {metric === 'voice' ? 'ボイス時間' : 'メッセージ数'}
        </span>
      </div>
      {entries.length === 0 ? (
        <p className="text-sm text-white/50">データがありません。</p>
      ) : (
        <>
          <ol className="space-y-2">
            {entries.map((e, idx) => (
              <li key={e.channel_id} className="flex items-center gap-3">
                <span className="w-6 text-right text-sm text-white/40">
                  #{idx + 1}
                </span>
                <span className="flex-1 truncate text-sm">#{e.name}</span>
                <span className="text-sm font-medium tabular-nums">
                  {metric === 'voice'
                    ? formatSeconds(e.voice_seconds)
                    : formatNumber(e.message_count)}
                </span>
              </li>
            ))}
          </ol>
          {moreHref ? (
            <div className="mt-3 text-right">
              <Link
                href={moreHref}
                className="text-xs text-white/60 hover:text-white"
              >
                もっと見る →
              </Link>
            </div>
          ) : null}
        </>
      )}
    </div>
  )
}
