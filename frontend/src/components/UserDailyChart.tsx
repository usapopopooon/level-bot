'use client'

import {
  Bar,
  BarChart,
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

export function UserDailyChart({ points }: Props) {
  const data = points.map((p) => ({
    date: formatDateShort(p.date),
    messages: p.message_count,
    voiceHours: formatHoursDecimal(p.voice_seconds),
  }))

  return (
    <div className="h-72 w-full rounded-xl border border-white/10 bg-white/5 p-4">
      <ResponsiveContainer>
        <BarChart data={data} margin={{ top: 10, right: 10, left: -10, bottom: 0 }}>
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
          <Bar
            yAxisId="left"
            dataKey="messages"
            name="メッセージ"
            fill="#5865F2"
            radius={[4, 4, 0, 0]}
          />
          <Bar
            yAxisId="right"
            dataKey="voiceHours"
            name="ボイス (時間)"
            fill="#57F287"
            radius={[4, 4, 0, 0]}
          />
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}
