import { Fragment } from 'react'

import { formatNumber, formatSeconds } from '@/shared/format'

import type { HourlyActivityCell } from './types'

interface Props {
  cells: HourlyActivityCell[]
  days: number
}

const WEEKDAYS = ['月', '火', '水', '木', '金', '土', '日']

const INTENSITY_STOPS = [
  { at: 0, label: 'Quiet', color: '#16212a', glow: 'transparent' },
  { at: 20, label: 'Low', color: '#17444e', glow: 'rgba(45, 212, 191, 0.10)' },
  { at: 45, label: 'Active', color: '#2563eb', glow: 'rgba(96, 165, 250, 0.18)' },
  { at: 70, label: 'Busy', color: '#7c3aed', glow: 'rgba(168, 85, 247, 0.22)' },
  { at: 100, label: 'Peak', color: '#f59e0b', glow: 'rgba(245, 158, 11, 0.26)' },
]

function intensityStop(intensity: number) {
  if (intensity <= 0) return INTENSITY_STOPS[0]
  if (intensity < 35) return INTENSITY_STOPS[1]
  if (intensity < 60) return INTENSITY_STOPS[2]
  if (intensity < 85) return INTENSITY_STOPS[3]
  return INTENSITY_STOPS[4]
}

function cellTextColor(intensity: number): string {
  if (intensity >= 85) return '#fff7ed'
  if (intensity >= 35) return '#f8fafc'
  if (intensity > 0) return '#cbd5e1'
  return 'transparent'
}

function cellStyle(intensity: number): React.CSSProperties {
  const stop = intensityStop(intensity)
  return {
    background:
      intensity > 0
        ? `linear-gradient(145deg, color-mix(in srgb, ${stop.color} 88%, white 12%), ${stop.color})`
        : stop.color,
    boxShadow:
      intensity > 0
        ? `inset 0 1px 0 rgba(255,255,255,0.16), 0 0 18px ${stop.glow}`
        : 'inset 0 1px 0 rgba(255,255,255,0.05)',
    color: cellTextColor(intensity),
  }
}

function describeCell(cell: HourlyActivityCell): string {
  return [
    `${WEEKDAYS[cell.weekday]}曜 ${String(cell.hour).padStart(2, '0')}:00`,
    `アクティブ率 ${cell.intensity_percent}%`,
    `VC ${formatSeconds(cell.voice_seconds)}`,
    `アクティブ ${formatNumber(cell.active_users)}人`,
  ].join(' / ')
}

export function HourlyActivityHeatmap({ cells, days }: Props) {
  const byKey = new Map(cells.map((cell) => [`${cell.weekday}:${cell.hour}`, cell]))
  const maxCell = cells.reduce<HourlyActivityCell | null>(
    (max, cell) =>
      max === null || cell.voice_seconds > max.voice_seconds ? cell : max,
    null,
  )

  return (
    <div className="overflow-hidden rounded-xl border border-white/10 bg-[linear-gradient(180deg,rgba(255,255,255,0.075),rgba(255,255,255,0.035))] p-4 shadow-[0_18px_70px_rgba(0,0,0,0.22)]">
      <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold">VC時間帯ヒートマップ</h2>
          <p className="mt-1 text-xs text-white/45">
            直近 {days} 日 / Bot 除外済み
          </p>
        </div>
        {maxCell && maxCell.intensity_percent > 0 ? (
          <div className="rounded-lg border border-amber-300/20 bg-amber-300/10 px-3 py-2 text-right">
            <div className="text-[10px] font-semibold uppercase tracking-wide text-amber-100/60">
              Peak
            </div>
            <div className="text-sm font-semibold text-amber-50">
              {WEEKDAYS[maxCell.weekday]}曜 {String(maxCell.hour).padStart(2, '0')}:00
            </div>
          </div>
        ) : null}
      </div>

      <div className="overflow-x-auto pb-1">
        <div className="grid min-w-[560px] grid-cols-[2.5rem_repeat(7,minmax(0,1fr))] gap-1.5">
          <div />
          {WEEKDAYS.map((day) => (
            <div
              key={day}
              className="pb-1 text-center text-xs font-semibold text-white/60"
            >
              {day}
            </div>
          ))}

          {Array.from({ length: 24 }, (_, hour) => (
            <Fragment key={hour}>
              <div
                key={`hour-${hour}`}
                className="flex h-8 items-center justify-end pr-2 text-xs tabular-nums text-white/45"
              >
                {String(hour).padStart(2, '0')}
              </div>
              {Array.from({ length: 7 }, (_, weekday) => {
                const cell =
                  byKey.get(`${weekday}:${hour}`) ?? {
                    weekday,
                    hour,
                    voice_seconds: 0,
                    active_users: 0,
                    intensity_percent: 0,
                  }
                const intensity = cell.intensity_percent
                return (
                  <div
                    key={`${weekday}-${hour}`}
                    title={describeCell(cell)}
                    aria-label={describeCell(cell)}
                    className="flex h-8 items-center justify-center rounded-md border border-white/10 text-[11px] font-semibold tabular-nums transition duration-150 hover:scale-[1.04] hover:border-white/35 hover:brightness-125"
                    style={cellStyle(intensity)}
                  >
                    {intensity > 0 ? `${intensity}%` : null}
                  </div>
                )
              })}
            </Fragment>
          ))}
        </div>
      </div>
      <div className="mt-4 flex flex-wrap items-center justify-between gap-3 border-t border-white/10 pt-3">
        <div className="text-xs text-white/40">色が明るいほどVCが集中している時間帯です</div>
        <div className="flex items-center gap-2">
          {INTENSITY_STOPS.map((stop) => (
            <div key={stop.at} className="flex items-center gap-1.5">
              <span
                className="h-3 w-5 rounded-sm border border-white/10"
                style={{ backgroundColor: stop.color }}
              />
              <span className="text-[10px] font-medium text-white/40">
                {stop.label}
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
