import Link from 'next/link'

import { formatEntryValue, metricLabel } from './metricFormat'
import type { LeaderboardEntry, Metric } from './types'

interface Props {
  guildId: string
  entries: LeaderboardEntry[]
  metric: Metric
  title: string
  days?: number
}

export function UserLeaderboardCard({
  guildId,
  entries,
  metric,
  title,
  days,
}: Props) {
  const moreHref = `/g/${guildId}/ranking?type=users&metric=${metric}${
    days ? `&days=${days}` : ''
  }`
  return (
    <div className="rounded-xl border border-white/10 bg-white/5 p-4">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-lg font-semibold">{title}</h2>
        <span className="text-xs text-white/40">{metricLabel(metric)}</span>
      </div>
      {entries.length === 0 ? (
        <p className="text-sm text-white/50">データがありません。</p>
      ) : (
        <>
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
                  {formatEntryValue(e, metric)}
                </span>
              </li>
            ))}
          </ol>
          <div className="mt-3 text-right">
            <Link
              href={moreHref}
              className="text-xs text-white/60 hover:text-white"
            >
              もっと見る →
            </Link>
          </div>
        </>
      )}
    </div>
  )
}
