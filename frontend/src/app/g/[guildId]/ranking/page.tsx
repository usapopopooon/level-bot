import Link from 'next/link'
import { notFound } from 'next/navigation'

import { RankingLoadMore } from '@/components/RankingLoadMore'
import {
  apiFetch,
  type ChannelLeaderboardEntry,
  type GuildSummary,
  type LeaderboardEntry,
} from '@/lib/api'

export const dynamic = 'force-dynamic'

const PAGE_SIZE = 50

interface Props {
  params: Promise<{ guildId: string }>
  searchParams: Promise<{
    type?: string
    metric?: string
    days?: string
  }>
}

type RankingType = 'users' | 'channels'
type Metric = 'messages' | 'voice'

function parseType(v: string | undefined): RankingType {
  return v === 'channels' ? 'channels' : 'users'
}

function parseMetric(v: string | undefined): Metric {
  return v === 'voice' ? 'voice' : 'messages'
}

function buildTitle(type: RankingType, metric: Metric): string {
  const subject = type === 'users' ? 'ユーザー' : 'チャンネル'
  const axis = metric === 'voice' ? 'ボイス時間' : 'メッセージ数'
  return `${subject}ランキング (${axis})`
}

export default async function RankingPage({ params, searchParams }: Props) {
  const { guildId } = await params
  const { type: typeRaw, metric: metricRaw, days: daysRaw } = await searchParams

  const type = parseType(typeRaw)
  const metric = parseMetric(metricRaw)
  const dayCount = Math.max(1, Math.min(365, Number(daysRaw) || 30))

  const summaryPromise = apiFetch<GuildSummary>(
    `/api/v1/guilds/${guildId}/summary?days=${dayCount}`,
  )

  const initialPromise =
    type === 'users'
      ? apiFetch<LeaderboardEntry[]>(
          `/api/v1/guilds/${guildId}/leaderboard/users?days=${dayCount}&metric=${metric}&limit=${PAGE_SIZE}&offset=0`,
        )
      : apiFetch<ChannelLeaderboardEntry[]>(
          `/api/v1/guilds/${guildId}/leaderboard/channels?days=${dayCount}&metric=${metric}&limit=${PAGE_SIZE}&offset=0`,
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
            {s.name} · 直近 {dayCount} 日
          </p>
        </div>
      </header>

      <section className="rounded-xl border border-white/10 bg-white/5 p-4">
        {type === 'users' ? (
          <RankingLoadMore
            type="users"
            guildId={guildId}
            metric={metric}
            days={dayCount}
            pageSize={PAGE_SIZE}
            initial={(initial.data as LeaderboardEntry[] | null) ?? []}
          />
        ) : (
          <RankingLoadMore
            type="channels"
            guildId={guildId}
            metric={metric}
            days={dayCount}
            pageSize={PAGE_SIZE}
            initial={(initial.data as ChannelLeaderboardEntry[] | null) ?? []}
          />
        )}
      </section>
    </div>
  )
}
