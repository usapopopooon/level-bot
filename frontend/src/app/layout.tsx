import type { Metadata } from 'next'
import Link from 'next/link'

import { LogoutButton } from '@/features/auth/LogoutButton'

import './globals.css'

const joinServerUrl =
  process.env.NEXT_PUBLIC_JOIN_SERVER_URL || 'https://discord.com/invite/chill-cafe'

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
            <div className="flex items-center gap-3">
              <a
                href={joinServerUrl}
                target="_blank"
                rel="noreferrer"
                className="text-sm font-medium text-white/70 transition hover:text-white"
              >
                Join Server
              </a>
              <LogoutButton />
            </div>
          </div>
        </header>
        <main className="mx-auto max-w-6xl px-4 py-6">{children}</main>
      </body>
    </html>
  )
}
