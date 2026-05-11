export interface LevelBreakdown {
  level: number
  xp: number
  current_floor: number
  next_floor: number
  progress: number
}

export interface UserLevels {
  total: LevelBreakdown
  voice: LevelBreakdown
  text: LevelBreakdown
  reactions_received: LevelBreakdown
  reactions_given: LevelBreakdown
  activity_rate: number
  activity_rate_window_days: number
}

export type LevelAxis =
  | 'total'
  | 'voice'
  | 'text'
  | 'reactions_received'
  | 'reactions_given'

export interface LevelLeaderboardEntry {
  user_id: string
  display_name: string
  avatar_url: string | null
  level: number
  xp: number
  activity_rate: number
}
