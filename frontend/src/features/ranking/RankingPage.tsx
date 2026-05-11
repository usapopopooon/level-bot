import Link from 'next/link'
import { notFound } from 'next/navigation'

import type { GuildSummary } from '@/features/dashboard/types'
import { apiFetch } from '@/shared/api'

import { metricLabel } from './metricFormat'
import { RankingLoadMore } from './RankingLoadMore'
import type {
  ChannelLeaderboardEntry,
  LeaderboardEntry,
  Metric,
} from './types'

const PAGE_SIZE = 50

export type RankingType = 'users' | 'channels'

interface Props {
  guildId: string
  type: RankingType
  metric: Metric
  days: number
}

function buildTitle(type: RankingType, metric: Metric): string {
  const subject = type === 'users' ? 'ユーザー' : 'チャンネル'
  return `${subject}ランキング (${metricLabel(metric)})`
}

export async function RankingPage({ guildId, type, metric, days }: Props) {
  const summaryPromise = apiFetch<GuildSummary>(
    `/api/v1/guilds/${guildId}/summary?days=${days}`,
  )

  const initialPromise =
    type === 'users'
      ? apiFetch<LeaderboardEntry[]>(
          `/api/v1/guilds/${guildId}/leaderboard/users?days=${days}&metric=${metric}&limit=${PAGE_SIZE}&offset=0`,
        )
      : apiFetch<ChannelLeaderboardEntry[]>(
          `/api/v1/guilds/${guildId}/leaderboard/channels?days=${days}&metric=${metric}&limit=${PAGE_SIZE}&offset=0`,
        )

  const [summary, initial] = await Promise.all([summaryPromise, initialPromise])

  if (summary.status === 404 || !summary.data) {
    notFound()
  }

  const s = summary.data!

  return (
    <div className="space-y-6">
      <Link
        href={`/g/${guildId}`}
        className="text-sm text-white/50 hover:text-white/80"
      >
        ← サーバーへ戻る
      </Link>

      <header className="flex items-center gap-4">
        {s.icon_url ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={s.icon_url}
            alt=""
            className="h-12 w-12 rounded-full bg-white/10"
          />
        ) : (
          <div className="h-12 w-12 rounded-full bg-white/10" />
        )}
        <div>
          <h1 className="text-2xl font-bold">{buildTitle(type, metric)}</h1>
          <p className="text-sm text-white/50">
            {s.name} · 直近 {days} 日
          </p>
        </div>
      </header>

      <section className="rounded-xl border border-white/10 bg-white/5 p-4">
        {type === 'users' ? (
          <RankingLoadMore
            type="users"
            guildId={guildId}
            metric={metric}
            days={days}
            pageSize={PAGE_SIZE}
            initial={(initial.data as LeaderboardEntry[] | null) ?? []}
          />
        ) : (
          <RankingLoadMore
            type="channels"
            guildId={guildId}
            metric={metric}
            days={days}
            pageSize={PAGE_SIZE}
            initial={(initial.data as ChannelLeaderboardEntry[] | null) ?? []}
          />
        )}
      </section>
    </div>
  )
}
