'use client'

import { usePathname, useRouter } from 'next/navigation'
import { useTransition } from 'react'

export function LogoutButton() {
  const router = useRouter()
  const pathname = usePathname()
  const [pending, startTransition] = useTransition()

  // 未ログイン用のログイン画面では表示する意味が無いので隠す
  if (pathname === '/login') return null

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
