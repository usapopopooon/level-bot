import { notFound } from 'next/navigation'

import { LevelLeaderboardCard } from '@/features/leveling/LevelLeaderboardCard'
import type { LevelLeaderboardEntry } from '@/features/leveling/types'
import { LevelRoleAwardsCard } from '@/features/guilds/LevelRoleAwardsCard'
import { ChannelLeaderboardCard } from '@/features/ranking/ChannelLeaderboardCard'
import type {
  ChannelLeaderboardEntry,
  LeaderboardEntry,
} from '@/features/ranking/types'
import { UserLeaderboardCard } from '@/features/ranking/UserLeaderboardCard'
import { apiFetch } from '@/shared/api'
import { formatNumber, formatSeconds } from '@/shared/format'

import { DailyChart } from './DailyChart'
import { StatCard } from './StatCard'
import type { DailyPoint, GuildSummary } from './types'

interface Props {
  guildId: string
  days: number
}

interface RoleOption {
  role_id: string
  role_name: string
  position: number
  is_managed: boolean
}

interface LevelRoleAward {
  slot: number
  level: number
  role_id: string
  role_name: string
}

export async function DashboardPage({ guildId, days }: Props) {
  const [
    summary,
    daily,
    msgUsers,
    voiceUsers,
    reactRecvUsers,
    reactGivenUsers,
    msgChannels,
    voiceChannels,
    reactRecvChannels,
    reactGivenChannels,
    levelTotal,
    levelVoice,
    levelText,
    levelReactRecv,
    levelReactGiven,
    roleOptions,
    roleRules,
  ] = await Promise.all([
    apiFetch<GuildSummary>(`/api/v1/guilds/${guildId}/summary?days=${days}`),
    apiFetch<DailyPoint[]>(`/api/v1/guilds/${guildId}/daily?days=${days}`),
    apiFetch<LeaderboardEntry[]>(
      `/api/v1/guilds/${guildId}/leaderboard/users?days=${days}&metric=messages&limit=10`,
    ),
    apiFetch<LeaderboardEntry[]>(
      `/api/v1/guilds/${guildId}/leaderboard/users?days=${days}&metric=voice&limit=10`,
    ),
    apiFetch<LeaderboardEntry[]>(
      `/api/v1/guilds/${guildId}/leaderboard/users?days=${days}&metric=reactions_received&limit=10`,
    ),
    apiFetch<LeaderboardEntry[]>(
      `/api/v1/guilds/${guildId}/leaderboard/users?days=${days}&metric=reactions_given&limit=10`,
    ),
    apiFetch<ChannelLeaderboardEntry[]>(
      `/api/v1/guilds/${guildId}/leaderboard/channels?days=${days}&metric=messages&limit=10`,
    ),
    apiFetch<ChannelLeaderboardEntry[]>(
      `/api/v1/guilds/${guildId}/leaderboard/channels?days=${days}&metric=voice&limit=10`,
    ),
    apiFetch<ChannelLeaderboardEntry[]>(
      `/api/v1/guilds/${guildId}/leaderboard/channels?days=${days}&metric=reactions_received&limit=10`,
    ),
    apiFetch<ChannelLeaderboardEntry[]>(
      `/api/v1/guilds/${guildId}/leaderboard/channels?days=${days}&metric=reactions_given&limit=10`,
    ),
    apiFetch<LevelLeaderboardEntry[]>(
      `/api/v1/guilds/${guildId}/levels/leaderboard?axis=total&limit=10`,
    ),
    apiFetch<LevelLeaderboardEntry[]>(
      `/api/v1/guilds/${guildId}/levels/leaderboard?axis=voice&limit=10`,
    ),
    apiFetch<LevelLeaderboardEntry[]>(
      `/api/v1/guilds/${guildId}/levels/leaderboard?axis=text&limit=10`,
    ),
    apiFetch<LevelLeaderboardEntry[]>(
      `/api/v1/guilds/${guildId}/levels/leaderboard?axis=reactions_received&limit=10`,
    ),
    apiFetch<LevelLeaderboardEntry[]>(
      `/api/v1/guilds/${guildId}/levels/leaderboard?axis=reactions_given&limit=10`,
    ),
    apiFetch<RoleOption[]>(`/api/v1/guilds/${guildId}/roles`),
    apiFetch<LevelRoleAward[]>(`/api/v1/guilds/${guildId}/level-role-awards`),
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

      <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-5">
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
          label="リアクション (受)"
          value={formatNumber(s.total_reactions_received)}
          hint={`${s.days} 日合計`}
        />
        <StatCard
          label="リアクション (送)"
          value={formatNumber(s.total_reactions_given)}
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

      <section className="space-y-3">
        <h2 className="text-lg font-semibold">⭐ レベルランキング</h2>
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          <LevelLeaderboardCard
            guildId={guildId}
            entries={levelTotal.data ?? []}
            axis="total"
            title="総合"
          />
          <LevelLeaderboardCard
            guildId={guildId}
            entries={levelVoice.data ?? []}
            axis="voice"
            title="🎙️ ボイス"
          />
          <LevelLeaderboardCard
            guildId={guildId}
            entries={levelText.data ?? []}
            axis="text"
            title="💬 テキスト"
          />
          <LevelLeaderboardCard
            guildId={guildId}
            entries={levelReactRecv.data ?? []}
            axis="reactions_received"
            title="💖 リアクション (受)"
          />
          <LevelLeaderboardCard
            guildId={guildId}
            entries={levelReactGiven.data ?? []}
            axis="reactions_given"
            title="👍 リアクション (送)"
          />
        </div>
      </section>

      <LevelRoleAwardsCard
        guildId={guildId}
        roles={roleOptions.data ?? []}
        initialRules={roleRules.data ?? []}
      />

      <section className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <UserLeaderboardCard
          guildId={guildId}
          entries={msgUsers.data ?? []}
          metric="messages"
          title="🏆 メッセージ"
          days={days}
        />
        <UserLeaderboardCard
          guildId={guildId}
          entries={voiceUsers.data ?? []}
          metric="voice"
          title="🎙️ ボイス"
          days={days}
        />
        <UserLeaderboardCard
          guildId={guildId}
          entries={reactRecvUsers.data ?? []}
          metric="reactions_received"
          title="💖 リアクション (受)"
          days={days}
        />
        <UserLeaderboardCard
          guildId={guildId}
          entries={reactGivenUsers.data ?? []}
          metric="reactions_given"
          title="👍 リアクション (送)"
          days={days}
        />
        <ChannelLeaderboardCard
          guildId={guildId}
          entries={msgChannels.data ?? []}
          metric="messages"
          title="📈 チャンネル別 (メッセージ)"
          days={days}
        />
        <ChannelLeaderboardCard
          guildId={guildId}
          entries={voiceChannels.data ?? []}
          metric="voice"
          title="📈 チャンネル別 (ボイス)"
          days={days}
        />
        <ChannelLeaderboardCard
          guildId={guildId}
          entries={reactRecvChannels.data ?? []}
          metric="reactions_received"
          title="📈 チャンネル別 (リアクション 受)"
          days={days}
        />
        <ChannelLeaderboardCard
          guildId={guildId}
          entries={reactGivenChannels.data ?? []}
          metric="reactions_given"
          title="📈 チャンネル別 (リアクション 送)"
          days={days}
        />
      </section>
    </div>
  )
}
