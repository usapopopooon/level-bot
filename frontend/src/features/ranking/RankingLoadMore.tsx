'use client'

import Link from 'next/link'
import { useState, useTransition } from 'react'

import {
  loadChannelLeaderboardPage,
  loadUserLeaderboardPage,
} from './actions'
import { formatEntryValue } from './metricFormat'
import type {
  ChannelLeaderboardEntry,
  LeaderboardEntry,
  Metric,
} from './types'

interface UserProps {
  type: 'users'
  guildId: string
  metric: Metric
  days: number
  pageSize: number
  initial: LeaderboardEntry[]
}

interface ChannelProps {
  type: 'channels'
  guildId: string
  metric: Metric
  days: number
  pageSize: number
  initial: ChannelLeaderboardEntry[]
}

type Props = UserProps | ChannelProps

export function RankingLoadMore(props: Props) {
  if (props.type === 'users') {
    return <UserList {...props} />
  }
  return <ChannelList {...props} />
}

function UserList({
  guildId,
  metric,
  days,
  pageSize,
  initial,
}: UserProps) {
  const [entries, setEntries] = useState<LeaderboardEntry[]>(initial)
  const [done, setDone] = useState(initial.length < pageSize)
  const [error, setError] = useState<string | null>(null)
  const [pending, startTransition] = useTransition()

  const handleLoadMore = () => {
    setError(null)
    startTransition(async () => {
      const next = await loadUserLeaderboardPage({
        guildId,
        metric,
        days,
        offset: entries.length,
        limit: pageSize,
      })
      if (next.length === 0 && entries.length === 0) {
        setError('読み込みに失敗しました')
        return
      }
      setEntries((prev) => [...prev, ...next])
      if (next.length < pageSize) setDone(true)
    })
  }

  return (
    <div>
      {entries.length === 0 ? (
        <p className="text-sm text-white/50">データがありません。</p>
      ) : (
        <ol className="space-y-2">
          {entries.map((e, idx) => (
            <li
              key={e.user_id}
              className="flex items-center gap-3 rounded-lg border border-white/5 bg-white/[0.02] px-3 py-2"
            >
              <span className="w-10 text-right text-sm text-white/40">
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
      )}
      <LoadMoreButton
        done={done}
        pending={pending}
        error={error}
        empty={entries.length === 0}
        onClick={handleLoadMore}
      />
    </div>
  )
}

function ChannelList({
  guildId,
  metric,
  days,
  pageSize,
  initial,
}: ChannelProps) {
  const [entries, setEntries] = useState<ChannelLeaderboardEntry[]>(initial)
  const [done, setDone] = useState(initial.length < pageSize)
  const [error, setError] = useState<string | null>(null)
  const [pending, startTransition] = useTransition()

  const handleLoadMore = () => {
    setError(null)
    startTransition(async () => {
      const next = await loadChannelLeaderboardPage({
        guildId,
        metric,
        days,
        offset: entries.length,
        limit: pageSize,
      })
      if (next.length === 0 && entries.length === 0) {
        setError('読み込みに失敗しました')
        return
      }
      setEntries((prev) => [...prev, ...next])
      if (next.length < pageSize) setDone(true)
    })
  }

  return (
    <div>
      {entries.length === 0 ? (
        <p className="text-sm text-white/50">データがありません。</p>
      ) : (
        <ol className="space-y-2">
          {entries.map((e, idx) => (
            <li
              key={e.channel_id}
              className="flex items-center gap-3 rounded-lg border border-white/5 bg-white/[0.02] px-3 py-2"
            >
              <span className="w-10 text-right text-sm text-white/40">
                #{idx + 1}
              </span>
              <span className="flex-1 truncate text-sm">#{e.name}</span>
              <span className="text-sm font-medium tabular-nums">
                {formatEntryValue(e, metric)}
              </span>
            </li>
          ))}
        </ol>
      )}
      <LoadMoreButton
        done={done}
        pending={pending}
        error={error}
        empty={entries.length === 0}
        onClick={handleLoadMore}
      />
    </div>
  )
}

function LoadMoreButton({
  done,
  pending,
  error,
  empty,
  onClick,
}: {
  done: boolean
  pending: boolean
  error: string | null
  empty: boolean
  onClick: () => void
}) {
  if (empty) return null
  if (done) {
    return (
      <p className="mt-4 text-center text-xs text-white/40">これ以上はありません</p>
    )
  }
  return (
    <div className="mt-4 flex flex-col items-center gap-2">
      <button
        type="button"
        onClick={onClick}
        disabled={pending}
        className="rounded-lg border border-white/15 bg-white/5 px-4 py-2 text-sm hover:bg-white/10 disabled:opacity-50"
      >
        {pending ? '読み込み中…' : 'もっと読み込む'}
      </button>
      {error ? <p className="text-xs text-red-400">{error}</p> : null}
    </div>
  )
}
