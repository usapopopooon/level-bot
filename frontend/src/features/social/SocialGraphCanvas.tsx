'use client'

import { useEffect, useMemo, useRef } from 'react'

import {
  getVisibleSocialGraph,
  socialGraphWindowHref,
} from '@/features/social/graphModel'

export interface SocialGraphNode {
  user_id: string
  display_name: string
  avatar_url: string | null
  weight: number
  message_count: number
  voice_seconds: number
  reactions_received: number
  reactions_given: number
}

export interface SocialGraphEdge {
  source_user_id: string
  target_user_id: string
  weight: number
  voice_seconds: number
  voice_sessions: number
  replies: number
  reactions: number
}

export interface SocialGraph {
  guild_id: string
  days: number
  nodes: SocialGraphNode[]
  edges: SocialGraphEdge[]
}

interface Props {
  graph: SocialGraph
}

interface SimNode extends SocialGraphNode {
  x: number
  y: number
  vx: number
  vy: number
  radius: number
}

function hashString(value: string): number {
  let hash = 2166136261
  for (let i = 0; i < value.length; i += 1) {
    hash ^= value.charCodeAt(i)
    hash = Math.imul(hash, 16777619)
  }
  return hash >>> 0
}

function seededUnit(seed: number): number {
  const next = Math.sin(seed * 12.9898) * 43758.5453
  return next - Math.floor(next)
}

function initials(name: string): string {
  const compact = name.trim()
  if (!compact) return '?'
  return Array.from(compact).slice(0, 2).join('').toUpperCase()
}

export function SocialGraphCanvas({ graph }: Props) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null)
  const imageCache = useRef<Map<string, HTMLImageElement>>(new Map())
  const visibleGraph = useMemo(() => getVisibleSocialGraph(graph), [graph])
  const { nodes, edges } = visibleGraph

  const windows = [7, 30, 90, 365]

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return

    const context = canvas.getContext('2d')
    if (!context) return
    const el = canvas
    const ctx = context

    let width = 0
    let height = 0
    let frame = 0
    let animationId = 0
    const maxWeight = Math.max(1, ...nodes.map((node) => node.weight))
    const maxEdgeWeight = Math.max(1, ...edges.map((edge) => edge.weight))
    const simNodes: SimNode[] = nodes.map((node) => {
      const seed = hashString(
        `${node.user_id}:${graph.days}:${Math.round(node.weight)}`,
      )
      const angle = seededUnit(seed) * Math.PI * 2
      const ring = 0.18 + seededUnit(seed + 7) * 0.28
      return {
        ...node,
        x: 0.5 + Math.cos(angle) * ring,
        y: 0.5 + Math.sin(angle) * ring,
        vx: (seededUnit(seed + 13) - 0.5) * 0.002,
        vy: (seededUnit(seed + 29) - 0.5) * 0.002,
        radius: 17 + Math.sqrt(node.weight / maxWeight) * 15,
      }
    })
    const nodeById = new Map(simNodes.map((node) => [node.user_id, node]))

    function resize() {
      const rect = el.getBoundingClientRect()
      const dpr = window.devicePixelRatio || 1
      width = Math.max(320, rect.width)
      height = Math.max(360, rect.height)
      el.width = Math.floor(width * dpr)
      el.height = Math.floor(height * dpr)
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    }

    function ensureImage(node: SimNode) {
      if (!node.avatar_url || imageCache.current.has(node.user_id)) return
      const image = new Image()
      image.crossOrigin = 'anonymous'
      image.src = node.avatar_url
      imageCache.current.set(node.user_id, image)
    }

    function simulate() {
      const centerX = 0.5
      const centerY = 0.5

      for (let i = 0; i < simNodes.length; i += 1) {
        const a = simNodes[i]
        for (let j = i + 1; j < simNodes.length; j += 1) {
          const b = simNodes[j]
          const dx = a.x - b.x
          const dy = a.y - b.y
          const distanceSq = Math.max(dx * dx + dy * dy, 0.0009)
          const force = 0.000035 / distanceSq
          a.vx += dx * force
          a.vy += dy * force
          b.vx -= dx * force
          b.vy -= dy * force
        }
      }

      for (const edge of edges) {
        const source = nodeById.get(edge.source_user_id)
        const target = nodeById.get(edge.target_user_id)
        if (!source || !target) continue
        const dx = target.x - source.x
        const dy = target.y - source.y
        const ideal = 0.17 + (1 - Math.min(edge.weight / maxEdgeWeight, 1)) * 0.2
        const distance = Math.max(Math.hypot(dx, dy), 0.001)
        const pull = (distance - ideal) * 0.0009
        source.vx += (dx / distance) * pull
        source.vy += (dy / distance) * pull
        target.vx -= (dx / distance) * pull
        target.vy -= (dy / distance) * pull
      }

      for (const node of simNodes) {
        const seed = hashString(`${node.user_id}:${graph.days}`)
        node.vx += (centerX - node.x) * 0.0007
        node.vy += (centerY - node.y) * 0.0007
        node.vx += Math.sin(frame * 0.009 + seed) * 0.00003
        node.vy += Math.cos(frame * 0.011 + seed) * 0.00003
        node.vx *= 0.91
        node.vy *= 0.91
        node.x = Math.min(0.94, Math.max(0.06, node.x + node.vx))
        node.y = Math.min(0.9, Math.max(0.1, node.y + node.vy))
      }
    }

    function drawBackground() {
      ctx.fillStyle = '#090909'
      ctx.fillRect(0, 0, width, height)

      ctx.save()
      ctx.globalAlpha = 0.14
      for (let i = 0; i < 42; i += 1) {
        const seed = i * 97
        const x =
          ((seededUnit(seed) * width + frame * (0.08 + seededUnit(seed + 2) * 0.2)) %
            (width + 80)) -
          40
        const y =
          seededUnit(seed + 1) * height +
          Math.sin(frame * 0.008 + seed) * 12
        const radius = 0.6 + seededUnit(seed + 3) * 1.5
        ctx.beginPath()
        ctx.arc(x, y, radius, 0, Math.PI * 2)
        ctx.fillStyle = '#ffffff'
        ctx.fill()
      }
      ctx.restore()
    }

    function draw() {
      frame += 1
      simulate()
      drawBackground()

      for (const edge of edges) {
        const source = nodeById.get(edge.source_user_id)
        const target = nodeById.get(edge.target_user_id)
        if (!source || !target) continue
        const strength = Math.min(edge.weight / maxEdgeWeight, 1)
        const sx = source.x * width
        const sy = source.y * height
        const tx = target.x * width
        const ty = target.y * height
        const midX = (sx + tx) / 2
        const midY = (sy + ty) / 2
        const bend = Math.sin(frame * 0.012 + hashString(source.user_id)) * 10

        ctx.beginPath()
        ctx.moveTo(sx, sy)
        ctx.quadraticCurveTo(midX, midY + bend, tx, ty)
        ctx.strokeStyle = `rgba(255,255,255,${0.1 + strength * 0.52})`
        ctx.lineWidth = 0.7 + strength * 4.2
        ctx.lineCap = 'round'
        ctx.stroke()
      }

      for (const node of simNodes) {
        ensureImage(node)
        const x = node.x * width
        const y = node.y * height
        const image = imageCache.current.get(node.user_id)
        const pulse =
          Math.sin(frame * 0.035 + hashString(`${node.user_id}:${graph.days}`)) *
          1.2
        const radius = node.radius + pulse

        ctx.save()
        ctx.beginPath()
        ctx.arc(x, y, radius + 4, 0, Math.PI * 2)
        ctx.fillStyle = 'rgba(255,255,255,0.08)'
        ctx.fill()
        ctx.beginPath()
        ctx.arc(x, y, radius + 1.5, 0, Math.PI * 2)
        ctx.strokeStyle = 'rgba(255,255,255,0.62)'
        ctx.lineWidth = 1.4
        ctx.stroke()

        ctx.beginPath()
        ctx.arc(x, y, radius, 0, Math.PI * 2)
        ctx.clip()
        if (image?.complete && image.naturalWidth > 0) {
          ctx.drawImage(image, x - radius, y - radius, radius * 2, radius * 2)
        } else {
          ctx.fillStyle = '#1d1d1d'
          ctx.fillRect(x - radius, y - radius, radius * 2, radius * 2)
          ctx.fillStyle = 'rgba(255,255,255,0.82)'
          ctx.font = `${Math.max(12, radius * 0.58)}px system-ui, sans-serif`
          ctx.textAlign = 'center'
          ctx.textBaseline = 'middle'
          ctx.fillText(initials(node.display_name), x, y)
        }
        ctx.restore()
      }

      animationId = requestAnimationFrame(draw)
    }

    resize()
    const observer = new ResizeObserver(resize)
    observer.observe(el)
    draw()

    return () => {
      cancelAnimationFrame(animationId)
      observer.disconnect()
    }
  }, [edges, graph.days, nodes])

  return (
    <div className="overflow-hidden rounded-lg border border-white/10 bg-black">
      <div className="flex flex-col gap-3 border-b border-white/10 px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h2 className="text-lg font-semibold">交流マップ</h2>
          <p className="text-sm text-white/45">
            直近 {graph.days} 日 / {graph.nodes.length} nodes / {graph.edges.length}{' '}
            edges
          </p>
        </div>
        <div className="flex w-fit overflow-hidden rounded-md border border-white/10">
          {windows.map((days) => (
            <a
              key={days}
              href={socialGraphWindowHref(days)}
              className={`px-3 py-1.5 text-sm transition ${
                graph.days === days
                  ? 'bg-white text-black'
                  : 'bg-transparent text-white/60 hover:bg-white/10 hover:text-white'
              }`}
            >
              {days}d
            </a>
          ))}
        </div>
      </div>
      <div className="relative h-[420px] sm:h-[520px]">
        {graph.nodes.length === 0 ? (
          <div className="flex h-full items-center justify-center text-sm text-white/45">
            交流データはまだありません
          </div>
        ) : (
          <canvas ref={canvasRef} className="h-full w-full" />
        )}
      </div>
    </div>
  )
}
