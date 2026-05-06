import Link from 'next/link'

import { apiFetch, type Guild } from '@/lib/api'
import { formatNumber } from '@/lib/format'

export const dynamic = 'force-dynamic'

export default async function HomePage() {
  const { data, error } = await apiFetch<Guild[]>('/api/v1/guilds')
  const guilds = data ?? []

  return (
    <div className="space-y-6">
      <section>
        <h1 className="text-2xl font-bold">サーバー一覧</h1>
        <p className="mt-1 text-sm text-white/60">
          Bot を導入しているサーバーの統計を閲覧できます。
        </p>
      </section>

      {error ? (
        <div className="rounded-xl border border-red-500/30 bg-red-500/10 p-4 text-sm text-red-200">
          API への接続に失敗しました: {error}
        </div>
      ) : null}

      {guilds.length === 0 ? (
        <p className="text-sm text-white/50">表示できるサーバーがまだありません。</p>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {guilds.map((g) => (
            <Link
              key={g.guild_id}
              href={`/g/${g.guild_id}`}
              className="group rounded-xl border border-white/10 bg-white/5 p-4 transition hover:border-white/30 hover:bg-white/10"
            >
              <div className="flex items-center gap-3">
                {g.icon_url ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img
                    src={g.icon_url}
                    alt=""
                    className="h-10 w-10 rounded-full bg-white/10"
                  />
                ) : (
                  <div className="h-10 w-10 rounded-full bg-white/10" />
                )}
                <div className="min-w-0 flex-1">
                  <div className="truncate font-semibold group-hover:underline">
                    {g.name}
                  </div>
                  <div className="text-xs text-white/40">
                    {formatNumber(g.member_count)} members
                  </div>
                </div>
              </div>
            </Link>
          ))}
        </div>
      )}
    </div>
  )
}
