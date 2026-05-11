import Link from 'next/link'
import { notFound } from 'next/navigation'

import { StatCard } from '@/features/dashboard/StatCard'
import { apiFetch } from '@/shared/api'
import { formatNumber, formatSeconds } from '@/shared/format'

import { TopChannelsList } from './TopChannelsList'
import type { UserProfile } from './types'
import { UserDailyChart } from './UserDailyChart'

interface Props {
  guildId: string
  userId: string
  days: number
}

export async function UserProfilePage({ guildId, userId, days }: Props) {
  const profileRes = await apiFetch<UserProfile>(
    `/api/v1/guilds/${guildId}/users/${userId}?days=${days}`,
  )

  if (profileRes.status === 404 || !profileRes.data) {
    notFound()
  }

  const p = profileRes.data!

  return (
    <div className="space-y-6">
      <Link
        href={`/g/${guildId}`}
        className="text-sm text-white/50 hover:text-white/80"
      >
        ← サーバーへ戻る
      </Link>

      <header className="flex items-center gap-4">
        {p.avatar_url ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={p.avatar_url}
            alt=""
            className="h-14 w-14 rounded-full bg-white/10"
          />
        ) : (
          <div className="h-14 w-14 rounded-full bg-white/10" />
        )}
        <div>
          <h1 className="text-2xl font-bold">{p.display_name}</h1>
          <p className="text-sm text-white/50">直近 {days} 日</p>
        </div>
      </header>

      <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4">
        <StatCard
          label="Messages"
          value={formatNumber(p.total_messages)}
          hint={p.rank_messages ? `rank #${p.rank_messages}` : undefined}
        />
        <StatCard
          label="Voice"
          value={formatSeconds(p.total_voice_seconds)}
          hint={p.rank_voice ? `rank #${p.rank_voice}` : undefined}
        />
        <StatCard
          label="リアクション (受)"
          value={formatNumber(p.total_reactions_received)}
          hint={
            p.rank_reactions_received
              ? `rank #${p.rank_reactions_received}`
              : undefined
          }
        />
        <StatCard
          label="リアクション (送)"
          value={formatNumber(p.total_reactions_given)}
          hint={
            p.rank_reactions_given
              ? `rank #${p.rank_reactions_given}`
              : undefined
          }
        />
        <StatCard
          label="Daily avg msg"
          value={formatNumber(Math.round(p.total_messages / days))}
        />
        <StatCard
          label="Daily avg voice"
          value={formatSeconds(Math.round(p.total_voice_seconds / days))}
        />
      </div>

      <section>
        <h2 className="mb-2 text-lg font-semibold">日別アクティビティ</h2>
        <UserDailyChart points={p.daily} />
      </section>

      <section>
        <TopChannelsList entries={p.top_channels} title="主な発言チャンネル" />
      </section>
    </div>
  )
}
