'use client'

import Link from 'next/link'
import { useRouter, useSearchParams } from 'next/navigation'
import { Suspense, useState } from 'react'

function LoginForm() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const [user, setUser] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const redirectParam = searchParams.get('redirect') ?? ''
  // open redirect 防止: スキーム付き / 別 origin (`//host` 始まり) は使わない
  const redirectPath =
    redirectParam.startsWith('/') && !redirectParam.startsWith('//')
      ? redirectParam
      : '/'

  async function handleSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault()
    setError('')
    setLoading(true)

    try {
      const res = await fetch('/api/v1/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ user, password }),
      })

      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        setError(body.detail || 'ログインに失敗しました')
        return
      }

      router.push(redirectPath)
      router.refresh()
    } catch {
      setError('ネットワークエラーです。再試行してください。')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="mx-auto mt-20 max-w-sm rounded-xl border border-white/10 bg-white/5 p-6">
      <h1 className="mb-4 text-xl font-semibold">ログイン</h1>
      <p className="mb-6 text-xs text-white/50">
        管理者の資格情報でサインインしてください。
      </p>
      <form onSubmit={handleSubmit} className="space-y-4">
        {error ? (
          <p className="rounded bg-red-500/10 px-3 py-2 text-xs text-red-300">
            {error}
          </p>
        ) : null}
        <label className="block">
          <span className="mb-1 block text-xs text-white/60">ユーザー名</span>
          <input
            type="text"
            autoComplete="username"
            value={user}
            onChange={(e) => setUser(e.target.value)}
            required
            className="w-full rounded-lg border border-white/10 bg-black/30 px-3 py-2 text-sm focus:border-white/30 focus:outline-none"
          />
        </label>
        <label className="block">
          <span className="mb-1 block text-xs text-white/60">パスワード</span>
          <input
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            className="w-full rounded-lg border border-white/10 bg-black/30 px-3 py-2 text-sm focus:border-white/30 focus:outline-none"
          />
        </label>
        <button
          type="submit"
          disabled={loading}
          className="w-full rounded-lg border border-white/20 bg-white/10 px-3 py-2 text-sm hover:bg-white/15 disabled:opacity-50"
        >
          {loading ? '送信中…' : 'サインイン'}
        </button>
      </form>
      <p className="mt-6 text-center text-xs text-white/30">
        <Link href="/">← トップへ戻る</Link>
      </p>
    </div>
  )
}

export default function LoginPage() {
  return (
    <Suspense>
      <LoginForm />
    </Suspense>
  )
}
