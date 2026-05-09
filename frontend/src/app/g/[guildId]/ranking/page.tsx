import {
  RankingPage,
  type RankingType,
} from '@/features/ranking/RankingPage'
import type { Metric } from '@/features/ranking/types'

export const dynamic = 'force-dynamic'

interface Props {
  params: Promise<{ guildId: string }>
  searchParams: Promise<{
    type?: string
    metric?: string
    days?: string
  }>
}

function parseType(v: string | undefined): RankingType {
  return v === 'channels' ? 'channels' : 'users'
}

function parseMetric(v: string | undefined): Metric {
  return v === 'voice' ? 'voice' : 'messages'
}

export default async function Page({ params, searchParams }: Props) {
  const { guildId } = await params
  const { type: typeRaw, metric: metricRaw, days: daysRaw } = await searchParams

  const type = parseType(typeRaw)
  const metric = parseMetric(metricRaw)
  const dayCount = Math.max(1, Math.min(365, Number(daysRaw) || 30))

  return (
    <RankingPage guildId={guildId} type={type} metric={metric} days={dayCount} />
  )
}
