'use server'

import { apiFetch } from '@/shared/api'

import type { ChannelLeaderboardEntry, LeaderboardEntry, Metric } from './types'

interface LoadPageArgs {
  guildId: string
  metric: Metric
  days: number
  offset: number
  limit: number
}

export async function loadUserLeaderboardPage(
  args: LoadPageArgs,
): Promise<LeaderboardEntry[]> {
  const { guildId, metric, days, offset, limit } = args
  const res = await apiFetch<LeaderboardEntry[]>(
    `/api/v1/guilds/${guildId}/leaderboard/users?days=${days}&metric=${metric}&limit=${limit}&offset=${offset}`,
  )
  return res.data ?? []
}

export async function loadChannelLeaderboardPage(
  args: LoadPageArgs,
): Promise<ChannelLeaderboardEntry[]> {
  const { guildId, metric, days, offset, limit } = args
  const res = await apiFetch<ChannelLeaderboardEntry[]>(
    `/api/v1/guilds/${guildId}/leaderboard/channels?days=${days}&metric=${metric}&limit=${limit}&offset=${offset}`,
  )
  return res.data ?? []
}
