import type { DailyPoint } from '@/features/dashboard/types'

/**
 * プロフィールの「主な発言チャンネル」レスポンス。
 * ranking 側の ChannelLeaderboardEntry と同型だが、ranking feature を
 * 削除しても user_profile が壊れないよう独立して定義する。
 */
export interface TopChannel {
  channel_id: string
  name: string
  message_count: number
  voice_seconds: number
}

export interface UserProfile {
  user_id: string
  display_name: string
  avatar_url: string | null
  total_messages: number
  total_voice_seconds: number
  rank_messages: number | null
  rank_voice: number | null
  daily: DailyPoint[]
  top_channels: TopChannel[]
}
