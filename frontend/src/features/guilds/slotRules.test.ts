import { describe, expect, it } from 'vitest'

import { removeSlotAndReindex } from './slotRules'

describe('removeSlotAndReindex', () => {
  it('removes rules in the target slot and shifts higher slots down', () => {
    const rules = [
      { slot: 1, level: 0, role_id: 'r1', role_name: 'A' },
      { slot: 2, level: 5, role_id: 'r2', role_name: 'B' },
      { slot: 3, level: 10, role_id: 'r3', role_name: 'C' },
      { slot: 3, level: 20, role_id: 'r4', role_name: 'D' },
    ]

    const next = removeSlotAndReindex(rules, 2)

    expect(next).toEqual([
      { slot: 1, level: 0, role_id: 'r1', role_name: 'A' },
      { slot: 2, level: 10, role_id: 'r3', role_name: 'C' },
      { slot: 2, level: 20, role_id: 'r4', role_name: 'D' },
    ])
  })

  it('keeps lower slots unchanged', () => {
    const rules = [
      { slot: 1, level: 1, role_id: 'r1', role_name: 'A' },
      { slot: 2, level: 2, role_id: 'r2', role_name: 'B' },
    ]

    const next = removeSlotAndReindex(rules, 2)

    expect(next).toEqual([{ slot: 1, level: 1, role_id: 'r1', role_name: 'A' }])
  })
})
