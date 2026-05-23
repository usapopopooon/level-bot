'use client'

import { useEffect, useMemo, useRef } from 'react'

import {
  getAdjacentUserIds,
  getGraphDistances,
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
  co_activity: number
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

interface FocusTarget {
  x: number
  y: number
  strength: number
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

function alphaForDistance(distance: number | undefined): number {
  if (distance === 0) return 1
  if (distance === 1) return 0.88
  if (distance === 2) return 0.46
  if (distance === undefined) return 0.16
  return 0.24
}

function scaleForDistance(distance: number | undefined): number {
  if (distance === 0) return 1.42
  if (distance === 1) return 1.08
  if (distance === 2) return 0.92
  if (distance === undefined) return 0.78
  return 0.84
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
    let hoveredUserId: string | null = null
    let focusAnchor: { x: number; y: number } | null = null
    let focusProgress = 0
    const maxWeight = Math.max(1, ...nodes.map((node) => node.weight))
    const maxEdgeWeight = Math.max(1, ...edges.map((edge) => edge.weight))
    const simNodes: SimNode[] = nodes.map((node, index) => {
      const seed = hashString(
        `${node.user_id}:${graph.days}:${Math.round(node.weight)}`,
      )
      const angle = index * 2.399963229728653 + seededUnit(seed) * 0.18
      const ring = 0.08 + Math.sqrt((index + 0.5) / Math.max(nodes.length, 1)) * 0.34
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
    const strongestEdgeByPair = new Map<string, number>()
    for (const edge of edges) {
      const key = [edge.source_user_id, edge.target_user_id].sort().join(':')
      strongestEdgeByPair.set(
        key,
        Math.max(strongestEdgeByPair.get(key) ?? 0, edge.weight),
      )
    }

    function edgeStrength(userA: string, userB: string) {
      const key = [userA, userB].sort().join(':')
      return Math.min((strongestEdgeByPair.get(key) ?? 0) / maxEdgeWeight, 1)
    }

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

    function nodeScreenPosition(node: SimNode) {
      return { x: node.x * width, y: node.y * height }
    }

    function findHoveredNode(clientX: number, clientY: number): SimNode | null {
      const rect = el.getBoundingClientRect()
      const x = clientX - rect.left
      const y = clientY - rect.top
      let closest: SimNode | null = null
      let closestDistance = Number.POSITIVE_INFINITY
      for (const node of simNodes) {
        const screen = nodeScreenPosition(node)
        const distance = Math.hypot(screen.x - x, screen.y - y)
        if (distance <= node.radius + 10 && distance < closestDistance) {
          closest = node
          closestDistance = distance
        }
      }
      return closest
    }

    function pointerPosition(clientX: number, clientY: number) {
      const rect = el.getBoundingClientRect()
      return {
        x: Math.min(0.9, Math.max(0.1, (clientX - rect.left) / Math.max(width, 1))),
        y: Math.min(0.84, Math.max(0.16, (clientY - rect.top) / Math.max(height, 1))),
      }
    }

    function pointerCanvasPosition(clientX: number, clientY: number) {
      const rect = el.getBoundingClientRect()
      return {
        x: clientX - rect.left,
        y: clientY - rect.top,
      }
    }

    function isPointerInsideFocusedNode(clientX: number, clientY: number): boolean {
      if (!hoveredUserId) return false
      const node = nodeById.get(hoveredUserId)
      if (!node) return false
      const pointer = pointerCanvasPosition(clientX, clientY)
      const screen = nodeScreenPosition(node)
      const focusedRadius = node.radius * scaleForDistance(0)
      return Math.hypot(screen.x - pointer.x, screen.y - pointer.y) <= focusedRadius + 8
    }

    function focusTargets(): Map<string, FocusTarget> {
      const targets = new Map<string, FocusTarget>()
      if (!hoveredUserId || !focusAnchor || focusProgress <= 0.01) return targets

      const adjacentIds = getAdjacentUserIds(edges, hoveredUserId)
      const neighbors = simNodes
        .filter((node) => adjacentIds.has(node.user_id))
        .sort(
          (a, b) =>
            edgeStrength(hoveredUserId ?? '', b.user_id) -
            edgeStrength(hoveredUserId ?? '', a.user_id),
        )
      const others = simNodes.filter(
        (node) => node.user_id !== hoveredUserId && !adjacentIds.has(node.user_id),
      )

      targets.set(hoveredUserId, {
        x: focusAnchor.x,
        y: focusAnchor.y,
        strength: 0.16,
      })
      const neighborCount = Math.max(neighbors.length, 1)
      for (const [index, node] of neighbors.entries()) {
        const strength = edgeStrength(hoveredUserId, node.user_id)
        const angle = index * 2.399963229728653 + strength * 0.35
        const ring = 0.16 + (1 - strength) * 0.12
        targets.set(node.user_id, {
          x: Math.min(0.92, Math.max(0.08, focusAnchor.x + Math.cos(angle) * ring)),
          y: Math.min(
            0.86,
            Math.max(0.14, focusAnchor.y + Math.sin(angle) * ring),
          ),
          strength: 0.06 + 0.04 / neighborCount,
        })
      }

      for (const [index, node] of others.entries()) {
        const angle = index * 2.399963229728653
        const ring = 0.4
        targets.set(node.user_id, {
          x: 0.5 + Math.cos(angle) * ring,
          y: 0.5 + Math.sin(angle) * ring * 0.78,
          strength: 0.012,
        })
      }
      return targets
    }

    function simulate() {
      const centerX = 0.5
      const centerY = 0.5
      focusProgress += ((hoveredUserId ? 1 : 0) - focusProgress) * 0.08
      const targets = focusTargets()

      for (let i = 0; i < simNodes.length; i += 1) {
        const a = simNodes[i]
        for (let j = i + 1; j < simNodes.length; j += 1) {
          const b = simNodes[j]
          const dx = a.x - b.x
          const dy = a.y - b.y
          const distanceSq = Math.max(dx * dx + dy * dy, 0.0009)
          const force = 0.000008 / distanceSq
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
        const ideal = 0.09 + (1 - Math.min(edge.weight / maxEdgeWeight, 1)) * 0.16
        const distance = Math.max(Math.hypot(dx, dy), 0.001)
        const pull = (distance - ideal) * 0.0026
        source.vx += (dx / distance) * pull
        source.vy += (dy / distance) * pull
        target.vx -= (dx / distance) * pull
        target.vy -= (dy / distance) * pull
      }

      for (const node of simNodes) {
        if (node.user_id === hoveredUserId && focusAnchor) {
          node.x = focusAnchor.x
          node.y = focusAnchor.y
          node.vx = 0
          node.vy = 0
          continue
        }

        const seed = hashString(`${node.user_id}:${graph.days}`)
        node.vx += (centerX - node.x) * 0.0024
        node.vy += (centerY - node.y) * 0.0024
        const target = targets.get(node.user_id)
        if (target) {
          node.vx += (target.x - node.x) * target.strength * focusProgress
          node.vy += (target.y - node.y) * target.strength * focusProgress
        }
        node.vx += Math.sin(frame * 0.009 + seed) * 0.00003
        node.vy += Math.cos(frame * 0.011 + seed) * 0.00003
        node.vx *= 0.86
        node.vy *= 0.86
        node.x += node.vx
        node.y += node.vy
        if (node.x < 0.08 || node.x > 0.92) {
          node.x = Math.min(0.92, Math.max(0.08, node.x))
          node.vx *= -0.35
        }
        if (node.y < 0.14 || node.y > 0.86) {
          node.y = Math.min(0.86, Math.max(0.14, node.y))
          node.vy *= -0.35
        }
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
      const focusedAdjacentIds = hoveredUserId
        ? getAdjacentUserIds(edges, hoveredUserId)
        : null
      const focusedDistances = hoveredUserId
        ? getGraphDistances(edges, hoveredUserId)
        : null

      for (const edge of edges) {
        const source = nodeById.get(edge.source_user_id)
        const target = nodeById.get(edge.target_user_id)
        if (!source || !target) continue
        const strength = Math.min(edge.weight / maxEdgeWeight, 1)
        const edgeFocused =
          !hoveredUserId ||
          edge.source_user_id === hoveredUserId ||
          edge.target_user_id === hoveredUserId
        const sourceDistance = focusedDistances?.get(edge.source_user_id)
        const targetDistance = focusedDistances?.get(edge.target_user_id)
        const nearestDistance =
          sourceDistance === undefined
            ? targetDistance
            : targetDistance === undefined
              ? sourceDistance
              : Math.min(sourceDistance, targetDistance)
        const distanceAlpha = alphaForDistance(nearestDistance)
        const focusAlpha =
          1 -
          focusProgress *
            (edgeFocused ? 1 - distanceAlpha * 1.05 : 1 - distanceAlpha)
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
        const lineAlpha = Math.min(1, (0.1 + strength * 0.52) * focusAlpha)
        ctx.strokeStyle = `rgba(255,255,255,${lineAlpha})`
        ctx.lineWidth =
          (0.7 + strength * 4.2) *
          (hoveredUserId ? 0.5 + distanceAlpha * 0.7 : 1)
        ctx.lineCap = 'round'
        ctx.stroke()
      }

      for (const node of simNodes) {
        ensureImage(node)
        const adjacent =
          hoveredUserId !== null &&
          (node.user_id === hoveredUserId ||
            (focusedAdjacentIds?.has(node.user_id) ?? false))
        const distance = focusedDistances?.get(node.user_id)
        const distanceAlpha = alphaForDistance(distance)
        const nodeAlpha =
          !hoveredUserId || adjacent
            ? 1 - focusProgress * (1 - distanceAlpha)
            : Math.max(0.12, 1 - focusProgress * (1 - distanceAlpha))
        const x = node.x * width
        const y = node.y * height
        const image = imageCache.current.get(node.user_id)
        const pulse =
          Math.sin(frame * 0.035 + hashString(`${node.user_id}:${graph.days}`)) *
          1.2
        const focusScale = hoveredUserId
          ? 1 + (scaleForDistance(distance) - 1) * focusProgress
          : 1
        const radius = (node.radius + pulse) * focusScale

        ctx.save()
        ctx.globalAlpha = nodeAlpha
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
    function onPointerMove(event: PointerEvent) {
      if (hoveredUserId && isPointerInsideFocusedNode(event.clientX, event.clientY)) {
        return
      }
      if (hoveredUserId) {
        hoveredUserId = null
        focusAnchor = null
        el.style.cursor = 'default'
      }
      const hovered = findHoveredNode(event.clientX, event.clientY)
      if (hovered) {
        hoveredUserId = hovered.user_id
        focusAnchor = pointerPosition(event.clientX, event.clientY)
        el.style.cursor = 'pointer'
      } else {
        hoveredUserId = null
        focusAnchor = null
        el.style.cursor = 'default'
      }
    }
    function onPointerLeave() {
      hoveredUserId = null
      focusAnchor = null
      el.style.cursor = 'default'
    }
    el.addEventListener('pointermove', onPointerMove)
    el.addEventListener('pointerleave', onPointerLeave)
    draw()

    return () => {
      cancelAnimationFrame(animationId)
      observer.disconnect()
      el.removeEventListener('pointermove', onPointerMove)
      el.removeEventListener('pointerleave', onPointerLeave)
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
