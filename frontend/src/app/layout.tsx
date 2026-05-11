import type { Metadata } from 'next'
import Link from 'next/link'

import { LogoutButton } from '@/features/auth/LogoutButton'

import './globals.css'

export const metadata: Metadata = {
  title: 'Level Bot — Discord Server Stats',
  description: 'Public Discord server statistics dashboard',
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ja">
      <body className="min-h-screen">
        <header className="border-b border-white/10 bg-black/20 backdrop-blur">
          <div className="mx-auto flex max-w-6xl items-center justify-between px-4 py-3">
            <Link href="/" className="text-base font-semibold tracking-tight">
              📊 Level Bot
            </Link>
            <LogoutButton />
          </div>
        </header>
        <main className="mx-auto max-w-6xl px-4 py-6">{children}</main>
      </body>
    </html>
  )
}
