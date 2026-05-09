import { DashboardPage } from '@/features/dashboard/DashboardPage'

export const dynamic = 'force-dynamic'

interface Props {
  params: Promise<{ guildId: string }>
  searchParams: Promise<{ days?: string }>
}

export default async function GuildPage({ params, searchParams }: Props) {
  const { guildId } = await params
  const { days } = await searchParams
  const dayCount = Math.max(1, Math.min(365, Number(days) || 30))
  return <DashboardPage guildId={guildId} days={dayCount} />
}
