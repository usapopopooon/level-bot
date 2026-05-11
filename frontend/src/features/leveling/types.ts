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
}
