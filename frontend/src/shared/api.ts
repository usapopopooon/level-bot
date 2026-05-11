import { cookies } from 'next/headers'

const API_URL = process.env.API_URL || 'http://localhost:8000'

interface FetchResult<T> {
  data: T | null
  error: string | null
  status: number
}

export async function apiFetch<T>(path: string): Promise<FetchResult<T>> {
  const url = `${API_URL}${path}`
  // Server Component から呼ばれる前提なので、リクエストのクッキー (session) を
  // FastAPI 側へ転送して認証を維持する。
  const cookieStore = await cookies()
  const cookieHeader = cookieStore.toString()
  try {
    const response = await fetch(url, {
      cache: 'no-store',
      headers: {
        'Content-Type': 'application/json',
        ...(cookieHeader ? { Cookie: cookieHeader } : {}),
      },
    })
    if (!response.ok) {
      const text = await response.text()
      let detail = text
      try {
        const parsed = JSON.parse(text)
        detail = parsed.detail || parsed.message || text
      } catch {
        // pass-through
      }
      console.error(`[apiFetch] ${response.status} ${url}: ${detail}`)
      return { data: null, error: detail, status: response.status }
    }
    const data = (await response.json()) as T
    return { data, error: null, status: response.status }
  } catch (err) {
    // Server Component の fetch で起きるエラー (DNS / connection refused / TLS など) は
    // Next.js のデフォルトでは UI に "fetch failed" としか出ない。
    // 原因を Railway logs に流すために console.error で stack 込みで出す。
    const cause = err instanceof Error && 'cause' in err ? (err as { cause: unknown }).cause : undefined
    console.error(
      `[apiFetch] network error fetching ${url}\n  API_URL=${API_URL}\n  cause=`,
      cause,
      '\n  err=',
      err,
    )
    const message = err instanceof Error ? err.message : 'Unknown error'
    return { data: null, error: message, status: 0 }
  }
}
