export interface LeaderboardEntry {
  user_id: string
  display_name: string
  avatar_url: string | null
  message_count: number
  voice_seconds: number
}

export interface ChannelLeaderboardEntry {
  channel_id: string
  name: string
  message_count: number
  voice_seconds: number
}

export type Metric = 'messages' | 'voice'
