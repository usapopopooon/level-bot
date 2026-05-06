import { notFound } from 'next/navigation'

import { ChannelLeaderboard } from '@/components/ChannelLeaderboard'
import { DailyChart } from '@/components/DailyChart'
import { StatCard } from '@/components/StatCard'
import { UserLeaderboard } from '@/components/UserLeaderboard'
import {
  apiFetch,
  type ChannelLeaderboardEntry,
  type DailyPoint,
  type GuildSummary,
  type LeaderboardEntry,
} from '@/lib/api'
import { formatNumber, formatSeconds } from '@/lib/format'

export const dynamic = 'force-dynamic'

interface Props {
  params: Promise<{ guildId: string }>
  searchParams: Promise<{ days?: string }>
}

export default async function GuildPage({ params, searchParams }: Props) {
  const { guildId } = await params
  const { days } = await searchParams
  const dayCount = Math.max(1, Math.min(365, Number(days) || 30))

  const [summary, daily, msgUsers, voiceUsers, msgChannels, voiceChannels] =
    await Promise.all([
      apiFetch<GuildSummary>(
        `/api/v1/guilds/${guildId}/summary?days=${dayCount}`,
      ),
      apiFetch<DailyPoint[]>(`/api/v1/guilds/${guildId}/daily?days=${dayCount}`),
      apiFetch<LeaderboardEntry[]>(
        `/api/v1/guilds/${guildId}/leaderboard/users?days=${dayCount}&metric=messages&limit=10`,
      ),
      apiFetch<LeaderboardEntry[]>(
        `/api/v1/guilds/${guildId}/leaderboard/users?days=${dayCount}&metric=voice&limit=10`,
      ),
      apiFetch<ChannelLeaderboardEntry[]>(
        `/api/v1/guilds/${guildId}/leaderboard/channels?days=${dayCount}&metric=messages&limit=10`,
      ),
      apiFetch<ChannelLeaderboardEntry[]>(
        `/api/v1/guilds/${guildId}/leaderboard/channels?days=${dayCount}&metric=voice&limit=10`,
      ),
    ])

  if (summary.status === 404 || !summary.data) {
    notFound()
  }

  const s = summary.data!

  return (
    <div className="space-y-6">
      <header className="flex items-center gap-4">
        {s.icon_url ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={s.icon_url}
            alt=""
            className="h-14 w-14 rounded-full bg-white/10"
          />
        ) : (
          <div className="h-14 w-14 rounded-full bg-white/10" />
        )}
        <div>
          <h1 className="text-2xl font-bold">{s.name}</h1>
          <p className="text-sm text-white/50">
            直近 {s.days} 日のサーバー統計
          </p>
        </div>
      </header>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <StatCard
          label="Messages"
          value={formatNumber(s.total_messages)}
          hint={`${s.days} 日合計`}
        />
        <StatCard
          label="Voice"
          value={formatSeconds(s.total_voice_seconds)}
          hint={`${s.days} 日合計`}
        />
        <StatCard
          label="Active users"
          value={formatNumber(s.active_users)}
          hint={`${s.days} 日内に活動`}
        />
      </div>

      <section>
        <h2 className="mb-2 text-lg font-semibold">日別アクティビティ</h2>
        <DailyChart points={daily.data ?? []} />
      </section>

      <section className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <UserLeaderboard
          guildId={guildId}
          entries={msgUsers.data ?? []}
          metric="messages"
          title="🏆 メッセージ"
        />
        <UserLeaderboard
          guildId={guildId}
          entries={voiceUsers.data ?? []}
          metric="voice"
          title="🎙️ ボイス"
        />
        <ChannelLeaderboard
          entries={msgChannels.data ?? []}
          metric="messages"
          title="📈 チャンネル別 (メッセージ)"
        />
        <ChannelLeaderboard
          entries={voiceChannels.data ?? []}
          metric="voice"
          title="📈 チャンネル別 (ボイス)"
        />
      </section>
    </div>
  )
}
