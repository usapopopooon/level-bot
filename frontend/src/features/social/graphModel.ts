import type { SocialGraph, SocialGraphEdge, SocialGraphNode } from './SocialGraphCanvas'

export interface VisibleSocialGraph {
  nodes: SocialGraphNode[]
  edges: SocialGraphEdge[]
}

export function getVisibleSocialGraph(
  graph: SocialGraph,
  maxNodes = 48,
): VisibleSocialGraph {
  const nodes = graph.nodes.slice(0, maxNodes)
  const nodeIds = new Set(nodes.map((node) => node.user_id))
  const edges = graph.edges.filter(
    (edge) =>
      nodeIds.has(edge.source_user_id) && nodeIds.has(edge.target_user_id),
  )
  return { nodes, edges }
}

export function socialGraphWindowHref(days: number): string {
  return `?days=${days}`
}

export function getAdjacentUserIds(
  edges: SocialGraphEdge[],
  userId: string,
): Set<string> {
  const adjacent = new Set<string>()
  for (const edge of edges) {
    if (edge.source_user_id === userId) adjacent.add(edge.target_user_id)
    if (edge.target_user_id === userId) adjacent.add(edge.source_user_id)
  }
  return adjacent
}

export function getGraphDistances(
  edges: SocialGraphEdge[],
  startUserId: string,
): Map<string, number> {
  const adjacency = new Map<string, Set<string>>()
  for (const edge of edges) {
    if (!adjacency.has(edge.source_user_id)) {
      adjacency.set(edge.source_user_id, new Set())
    }
    if (!adjacency.has(edge.target_user_id)) {
      adjacency.set(edge.target_user_id, new Set())
    }
    adjacency.get(edge.source_user_id)?.add(edge.target_user_id)
    adjacency.get(edge.target_user_id)?.add(edge.source_user_id)
  }

  const distances = new Map<string, number>([[startUserId, 0]])
  const queue = [startUserId]
  for (let index = 0; index < queue.length; index += 1) {
    const userId = queue[index]
    const distance = distances.get(userId) ?? 0
    for (const next of adjacency.get(userId) ?? []) {
      if (distances.has(next)) continue
      distances.set(next, distance + 1)
      queue.push(next)
    }
  }
  return distances
}
