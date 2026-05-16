export interface SlotRule {
  slot: number
  level: number
  role_id: string
  role_name: string
}

export function removeSlotAndReindex(rules: SlotRule[], removedSlot: number): SlotRule[] {
  return rules
    .filter((r) => r.slot !== removedSlot)
    .map((r) => (r.slot > removedSlot ? { ...r, slot: r.slot - 1 } : r))
}
