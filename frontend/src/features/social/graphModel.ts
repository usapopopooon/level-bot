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
