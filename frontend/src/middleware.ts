import { NextResponse } from 'next/server'

import type { NextRequest } from 'next/server'

// 未認証でもアクセスを許可するパス。
// /api は rewrite で FastAPI に直送りされるので middleware で守らず、
// 個別の認証は FastAPI 側の auth middleware で処理する。
const PUBLIC_PATH_PREFIXES = ['/login', '/api', '/_next', '/favicon.ico']

export function middleware(request: NextRequest) {
  const { pathname, search } = request.nextUrl

  if (PUBLIC_PATH_PREFIXES.some((p) => pathname.startsWith(p))) {
    return NextResponse.next()
  }

  const session = request.cookies.get('session')
  if (!session) {
    const loginUrl = new URL('/login', request.url)
    loginUrl.searchParams.set('redirect', `${pathname}${search}`)
    return NextResponse.redirect(loginUrl)
  }

  return NextResponse.next()
}

export const config = {
  matcher: ['/((?!_next/static|_next/image|favicon.ico).*)'],
}
