import { NextRequest, NextResponse } from 'next/server'

/**
 * /api/v1/* を FastAPI へ転送する Route Handler proxy。
 *
 * Next.js の rewrites は宛先 URL のポート部 (`:8000`) を route param と
 * 誤認するため、ここで自前 fetch を書いて回避している。
 *
 * - cookie / Authorization 等のヘッダは透過
 * - body はバイナリで透過 (POST 等の JSON も透過できる)
 * - レスポンスのヘッダ / status / body はそのまま返す
 */

const API_URL = process.env.API_URL || 'http://localhost:8000'

// このセクションは proxy なので Next.js の cache を効かせない
export const dynamic = 'force-dynamic'
export const runtime = 'nodejs'

async function forward(
  req: NextRequest,
  pathSegments: string[],
): Promise<NextResponse> {
  const search = req.nextUrl.search ?? ''
  const target = `${API_URL}/api/v1/${pathSegments.join('/')}${search}`

  // 元リクエストのヘッダから host を除いてコピー (上流の名前解決を壊さないため)
  const headers = new Headers()
  req.headers.forEach((value, key) => {
    if (key.toLowerCase() === 'host') return
    headers.set(key, value)
  })

  const init: RequestInit = {
    method: req.method,
    headers,
    redirect: 'manual',
  }
  if (req.method !== 'GET' && req.method !== 'HEAD') {
    init.body = await req.arrayBuffer()
  }

  const upstream = await fetch(target, init)
  const respHeaders = new Headers()
  upstream.headers.forEach((value, key) => {
    // content-encoding は Next.js が再圧縮するため透過しない
    if (key.toLowerCase() === 'content-encoding') return
    if (key.toLowerCase() === 'content-length') return
    respHeaders.set(key, value)
  })
  return new NextResponse(upstream.body, {
    status: upstream.status,
    headers: respHeaders,
  })
}

interface RouteContext {
  params: Promise<{ path: string[] }>
}

export async function GET(req: NextRequest, ctx: RouteContext) {
  return forward(req, (await ctx.params).path)
}

export async function POST(req: NextRequest, ctx: RouteContext) {
  return forward(req, (await ctx.params).path)
}

export async function PUT(req: NextRequest, ctx: RouteContext) {
  return forward(req, (await ctx.params).path)
}

export async function PATCH(req: NextRequest, ctx: RouteContext) {
  return forward(req, (await ctx.params).path)
}

export async function DELETE(req: NextRequest, ctx: RouteContext) {
  return forward(req, (await ctx.params).path)
}

export async function OPTIONS(req: NextRequest, ctx: RouteContext) {
  return forward(req, (await ctx.params).path)
}
