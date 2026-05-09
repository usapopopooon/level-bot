import { UserProfilePage } from '@/features/user_profile/UserProfilePage'

export const dynamic = 'force-dynamic'

interface Props {
  params: Promise<{ guildId: string; userId: string }>
  searchParams: Promise<{ days?: string }>
}

export default async function UserPage({ params, searchParams }: Props) {
  const { guildId, userId } = await params
  const { days } = await searchParams
  const dayCount = Math.max(1, Math.min(365, Number(days) || 30))
  return <UserProfilePage guildId={guildId} userId={userId} days={dayCount} />
}
