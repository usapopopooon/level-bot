export interface GuildSummary {
  guild_id: string
  name: string
  icon_url: string | null
  total_messages: number
  total_voice_seconds: number
  active_users: number
  days: number
}

export interface DailyPoint {
  date: string
  message_count: number
  voice_seconds: number
}
