import { describe, expect, it } from 'vitest'

import {
  getAdjacentUserIds,
  getVisibleSocialGraph,
  socialGraphWindowHref,
  type VisibleSocialGraph,
} from './graphModel'
import type { SocialGraph } from './SocialGraphCanvas'

const baseNode = {
  display_name: 'User',
  avatar_url: null,
  weight: 1,
  message_count: 0,
  voice_seconds: 0,
  reactions_received: 0,
  reactions_given: 0,
}

function graph(): SocialGraph {
  return {
    guild_id: '1001',
    days: 30,
    nodes: [
      { ...baseNode, user_id: '1', display_name: 'A' },
      { ...baseNode, user_id: '2', display_name: 'B' },
      { ...baseNode, user_id: '3', display_name: 'C' },
    ],
    edges: [
      {
        source_user_id: '1',
        target_user_id: '2',
        weight: 10,
        voice_seconds: 600,
        voice_sessions: 1,
        replies: 2,
        reactions: 3,
        co_activity: 0,
      },
      {
        source_user_id: '1',
        target_user_id: '3',
        weight: 5,
        voice_seconds: 0,
        voice_sessions: 0,
        replies: 1,
        reactions: 2,
        co_activity: 0,
      },
    ],
  }
}

describe('getVisibleSocialGraph', () => {
  it('keeps only edges whose endpoints are visible', () => {
    const visible: VisibleSocialGraph = getVisibleSocialGraph(graph(), 2)

    expect(visible.nodes.map((node) => node.user_id)).toEqual(['1', '2'])
    expect(visible.edges).toHaveLength(1)
    expect(visible.edges[0].source_user_id).toBe('1')
    expect(visible.edges[0].target_user_id).toBe('2')
  })

  it('keeps all edges when all endpoints are visible', () => {
    const visible = getVisibleSocialGraph(graph(), 3)

    expect(visible.nodes).toHaveLength(3)
    expect(visible.edges).toHaveLength(2)
  })
})

describe('socialGraphWindowHref', () => {
  it('builds the days query used by the reactive window controls', () => {
    expect(socialGraphWindowHref(90)).toBe('?days=90')
  })
})

describe('getAdjacentUserIds', () => {
  it('returns neighbors from either side of an edge', () => {
    expect(Array.from(getAdjacentUserIds(graph().edges, '1')).sort()).toEqual([
      '2',
      '3',
    ])
    expect(Array.from(getAdjacentUserIds(graph().edges, '2'))).toEqual(['1'])
  })
})
