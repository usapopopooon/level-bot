export interface LeaderboardEntry {
  user_id: string
  display_name: string
  avatar_url: string | null
  message_count: number
  voice_seconds: number
  reactions_received: number
  reactions_given: number
}

export interface ChannelLeaderboardEntry {
  channel_id: string
  name: string
  message_count: number
  voice_seconds: number
  reactions_received: number
  reactions_given: number
}

export type Metric = 'messages' | 'voice' | 'reactions_received' | 'reactions_given'
