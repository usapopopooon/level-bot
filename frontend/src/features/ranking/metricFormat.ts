import { formatNumber, formatSeconds } from '@/shared/format'

import type {
  ChannelLeaderboardEntry,
  LeaderboardEntry,
  Metric,
} from './types'

export const METRIC_LABELS: Record<Metric, string> = {
  messages: 'メッセージ数',
  voice: 'ボイス時間',
  reactions_received: 'リアクション (受)',
  reactions_given: 'リアクション (送)',
}

export function metricLabel(metric: Metric): string {
  return METRIC_LABELS[metric]
}

export function formatEntryValue(
  entry: LeaderboardEntry | ChannelLeaderboardEntry,
  metric: Metric,
): string {
  switch (metric) {
    case 'voice':
      return formatSeconds(entry.voice_seconds)
    case 'reactions_received':
      return formatNumber(entry.reactions_received)
    case 'reactions_given':
      return formatNumber(entry.reactions_given)
    case 'messages':
    default:
      return formatNumber(entry.message_count)
  }
}
