const API_URL = process.env.API_URL || 'http://localhost:8000'

interface FetchResult<T> {
  data: T | null
  error: string | null
  status: number
}

export async function apiFetch<T>(path: string): Promise<FetchResult<T>> {
  const url = `${API_URL}${path}`
  try {
    const response = await fetch(url, {
      cache: 'no-store',
      headers: { 'Content-Type': 'application/json' },
    })
    if (!response.ok) {
      const text = await response.text()
      let detail = text
      try {
        const parsed = JSON.parse(text)
        detail = parsed.detail || parsed.message || text
      } catch {
        // pass-through
      }
      return { data: null, error: detail, status: response.status }
    }
    const data = (await response.json()) as T
    return { data, error: null, status: response.status }
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Unknown error'
    return { data: null, error: message, status: 0 }
  }
}

// =============================================================================
// API types
// =============================================================================

export interface Guild {
  guild_id: string
  name: string
  icon_url: string | null
  member_count: number
}

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

export interface UserProfile {
  user_id: string
  display_name: string
  avatar_url: string | null
  total_messages: number
  total_voice_seconds: number
  rank_messages: number | null
  rank_voice: number | null
  daily: DailyPoint[]
  top_channels: ChannelLeaderboardEntry[]
}
