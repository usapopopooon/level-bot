import Link from 'next/link'
import { notFound } from 'next/navigation'

import { ChannelLeaderboard } from '@/components/ChannelLeaderboard'
import { StatCard } from '@/components/StatCard'
import { UserDailyChart } from '@/components/UserDailyChart'
import { apiFetch, type UserProfile } from '@/lib/api'
import { formatNumber, formatSeconds } from '@/lib/format'

export const dynamic = 'force-dynamic'

interface Props {
  params: Promise<{ guildId: string; userId: string }>
  searchParams: Promise<{ days?: string }>
}

export default async function UserPage({ params, searchParams }: Props) {
  const { guildId, userId } = await params
  const { days } = await searchParams
  const dayCount = Math.max(1, Math.min(365, Number(days) || 30))

  const profileRes = await apiFetch<UserProfile>(
    `/api/v1/guilds/${guildId}/users/${userId}?days=${dayCount}`,
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
          <p className="text-sm text-white/50">直近 {dayCount} 日</p>
        </div>
      </header>

      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
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
          label="Daily avg msg"
          value={formatNumber(Math.round(p.total_messages / dayCount))}
        />
        <StatCard
          label="Daily avg voice"
          value={formatSeconds(Math.round(p.total_voice_seconds / dayCount))}
        />
      </div>

      <section>
        <h2 className="mb-2 text-lg font-semibold">日別アクティビティ</h2>
        <UserDailyChart points={p.daily} />
      </section>

      <section>
        <ChannelLeaderboard
          entries={p.top_channels}
          metric="messages"
          title="主な発言チャンネル"
        />
      </section>
    </div>
  )
}
