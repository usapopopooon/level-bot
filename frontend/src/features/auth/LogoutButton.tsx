'use client'

import { useRouter } from 'next/navigation'
import { useTransition } from 'react'

export function LogoutButton() {
  const router = useRouter()
  const [pending, startTransition] = useTransition()

  const handleLogout = () => {
    startTransition(async () => {
      await fetch('/api/v1/auth/logout', {
        method: 'POST',
        credentials: 'include',
      })
      router.push('/login')
      router.refresh()
    })
  }

  return (
    <button
      type="button"
      onClick={handleLogout}
      disabled={pending}
      className="text-xs text-white/40 hover:text-white/70 disabled:opacity-50"
    >
      {pending ? '…' : 'ログアウト'}
    </button>
  )
}
