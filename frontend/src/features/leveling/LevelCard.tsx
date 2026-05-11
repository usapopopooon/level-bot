import { formatNumber } from '@/shared/format'

import type { LevelBreakdown } from './types'

interface Props {
  label: string
  emoji?: string
  breakdown: LevelBreakdown
  highlight?: boolean
}

export function LevelCard({ label, emoji, breakdown, highlight }: Props) {
  const ratio = Math.max(0, Math.min(1, breakdown.progress))
  const remaining = Math.max(0, breakdown.next_floor - breakdown.xp)
  const span = breakdown.next_floor - breakdown.current_floor
  return (
    <div
      className={`rounded-xl border p-4 ${
        highlight
          ? 'border-amber-400/40 bg-amber-400/5'
          : 'border-white/10 bg-white/5'
      }`}
    >
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-xs text-white/60">
          {emoji ? `${emoji} ` : ''}
          {label}
        </span>
        <span
          className={`tabular-nums ${
            highlight ? 'text-2xl font-bold' : 'text-lg font-semibold'
          }`}
        >
          Lv {breakdown.level}
        </span>
      </div>
      <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-white/10">
        <div
          className={`h-full ${highlight ? 'bg-amber-400' : 'bg-white/50'}`}
          style={{ width: `${ratio * 100}%` }}
        />
      </div>
      <div className="mt-1 flex justify-between text-[10px] text-white/40 tabular-nums">
        <span>{formatNumber(breakdown.xp)} XP</span>
        <span>
          {span > 0 ? `次まで ${formatNumber(remaining)}` : 'MAX'}
        </span>
      </div>
    </div>
  )
}
