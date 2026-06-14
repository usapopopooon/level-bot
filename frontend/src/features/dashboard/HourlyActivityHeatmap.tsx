import { Fragment } from 'react'

import { formatNumber, formatSeconds } from '@/shared/format'

import type { HourlyActivityCell } from './types'

interface Props {
  cells: HourlyActivityCell[]
  days: number
}

const WEEKDAYS = ['月', '火', '水', '木', '金', '土', '日']

function cellColor(intensity: number): string {
  if (intensity <= 0) return 'rgba(255, 255, 255, 0.03)'
  const alpha = 0.14 + Math.min(intensity, 100) / 100 * 0.72
  return `rgba(34, 197, 94, ${alpha})`
}

function cellTextColor(intensity: number): string {
  if (intensity >= 65) return '#ecfdf5'
  if (intensity >= 35) return '#bbf7d0'
  if (intensity > 0) return '#d1d5db'
  return 'transparent'
}

function describeCell(cell: HourlyActivityCell): string {
  return [
    `${WEEKDAYS[cell.weekday]}曜 ${String(cell.hour).padStart(2, '0')}:00`,
    `強度 ${cell.intensity_percent}%`,
    `メッセージ ${formatNumber(cell.message_count)}`,
    `VC ${formatSeconds(cell.voice_seconds)}`,
    `リアクション ${formatNumber(cell.reactions_received + cell.reactions_given)}`,
    `アクティブ ${formatNumber(cell.active_users)}人`,
  ].join(' / ')
}

export function HourlyActivityHeatmap({ cells, days }: Props) {
  const byKey = new Map(cells.map((cell) => [`${cell.weekday}:${cell.hour}`, cell]))
  const maxCell = cells.reduce<HourlyActivityCell | null>(
    (max, cell) =>
      max === null || cell.activity_score > max.activity_score ? cell : max,
    null,
  )

  return (
    <div className="rounded-xl border border-white/10 bg-white/5 p-4">
      <div className="mb-3 flex flex-wrap items-end justify-between gap-2">
        <div>
          <h2 className="text-lg font-semibold">時間帯ヒートマップ</h2>
          <p className="mt-1 text-xs text-white/45">
            直近 {days} 日 / Bot 除外済み
          </p>
        </div>
        {maxCell && maxCell.intensity_percent > 0 ? (
          <div className="text-right text-xs text-white/45">
            Peak {WEEKDAYS[maxCell.weekday]} {String(maxCell.hour).padStart(2, '0')}:00
          </div>
        ) : null}
      </div>

      <div className="overflow-x-auto pb-1">
        <div className="grid min-w-[520px] grid-cols-[2.25rem_repeat(7,minmax(0,1fr))] gap-1">
          <div />
          {WEEKDAYS.map((day) => (
            <div
              key={day}
              className="text-center text-sm font-semibold text-white/60"
            >
              {day}
            </div>
          ))}

          {Array.from({ length: 24 }, (_, hour) => (
            <Fragment key={hour}>
              <div
                key={`hour-${hour}`}
                className="flex h-8 items-center justify-end pr-2 text-sm tabular-nums text-white/50"
              >
                {String(hour).padStart(2, '0')}
              </div>
              {Array.from({ length: 7 }, (_, weekday) => {
                const cell =
                  byKey.get(`${weekday}:${hour}`) ?? {
                    weekday,
                    hour,
                    message_count: 0,
                    voice_seconds: 0,
                    reactions_received: 0,
                    reactions_given: 0,
                    active_users: 0,
                    activity_score: 0,
                    intensity_percent: 0,
                  }
                const intensity = cell.intensity_percent
                return (
                  <div
                    key={`${weekday}-${hour}`}
                    title={describeCell(cell)}
                    aria-label={describeCell(cell)}
                    className="flex h-8 items-center justify-center border border-white/10 text-sm font-medium tabular-nums shadow-[inset_0_0_0_1px_rgba(255,255,255,0.03)]"
                    style={{
                      backgroundColor: cellColor(intensity),
                      color: cellTextColor(intensity),
                    }}
                  >
                    {intensity > 0 ? `${intensity}%` : '0'}
                  </div>
                )
              })}
            </Fragment>
          ))}
        </div>
      </div>
    </div>
  )
}
