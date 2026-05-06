'use client'

import {
  Area,
  AreaChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

import type { DailyPoint } from '@/lib/api'
import { formatDateShort, formatHoursDecimal } from '@/lib/format'

interface Props {
  points: DailyPoint[]
}

export function DailyChart({ points }: Props) {
  const data = points.map((p) => ({
    date: formatDateShort(p.date),
    messages: p.message_count,
    voiceHours: formatHoursDecimal(p.voice_seconds),
  }))

  return (
    <div className="h-72 w-full rounded-xl border border-white/10 bg-white/5 p-4">
      <ResponsiveContainer>
        <AreaChart data={data} margin={{ top: 10, right: 10, left: -10, bottom: 0 }}>
          <defs>
            <linearGradient id="colorMessages" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor="#5865F2" stopOpacity={0.6} />
              <stop offset="95%" stopColor="#5865F2" stopOpacity={0} />
            </linearGradient>
            <linearGradient id="colorVoice" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor="#57F287" stopOpacity={0.6} />
              <stop offset="95%" stopColor="#57F287" stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid strokeDasharray="3 3" stroke="#ffffff15" />
          <XAxis dataKey="date" tick={{ fill: '#aaa', fontSize: 12 }} />
          <YAxis
            yAxisId="left"
            tick={{ fill: '#aaa', fontSize: 12 }}
            allowDecimals={false}
          />
          <YAxis
            yAxisId="right"
            orientation="right"
            tick={{ fill: '#aaa', fontSize: 12 }}
          />
          <Tooltip
            contentStyle={{
              background: '#1a1d24',
              border: '1px solid #ffffff20',
              borderRadius: 8,
            }}
            labelStyle={{ color: '#fff' }}
          />
          <Legend wrapperStyle={{ color: '#ddd' }} />
          <Area
            yAxisId="left"
            type="monotone"
            dataKey="messages"
            name="メッセージ"
            stroke="#5865F2"
            fill="url(#colorMessages)"
            strokeWidth={2}
          />
          <Area
            yAxisId="right"
            type="monotone"
            dataKey="voiceHours"
            name="ボイス (時間)"
            stroke="#57F287"
            fill="url(#colorVoice)"
            strokeWidth={2}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  )
}
