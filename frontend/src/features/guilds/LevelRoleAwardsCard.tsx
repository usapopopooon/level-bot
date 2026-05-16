'use client'

import { useMemo, useState, useTransition } from 'react'
import { removeSlotAndReindex } from './slotRules'

interface RoleOption {
  role_id: string
  role_name: string
  position: number
  is_managed: boolean
}

interface Rule {
  slot: number
  level: number
  role_id: string
  role_name: string
}

interface Props {
  guildId: string
  roles: RoleOption[]
  initialRules: Rule[]
}

export function LevelRoleAwardsCard({ guildId, roles, initialRules }: Props) {
  const [rules, setRules] = useState<Rule[]>(initialRules)
  const [slotCount, setSlotCount] = useState<number>(
    Math.max(1, ...initialRules.map((r) => r.slot ?? 1)),
  )
  const [newLevels, setNewLevels] = useState<Record<number, number>>({})
  const [newRoleNameInputs, setNewRoleNameInputs] = useState<Record<number, string>>(
    {},
  )
  const [selectedRoleIds, setSelectedRoleIds] = useState<Record<number, string>>({})
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState<string | null>(null)
  const [pending, startTransition] = useTransition()

  const slots = useMemo(
    () => Array.from({ length: slotCount }, (_, i) => i + 1),
    [slotCount],
  )

  const sortedRules = useMemo(
    () => [...rules].sort((a, b) => a.slot - b.slot || a.level - b.level),
    [rules],
  )

  const rulesBySlot = useMemo(() => {
    const grouped = new Map<number, Rule[]>()
    for (const slot of slots) {
      grouped.set(slot, [])
    }
    for (const rule of sortedRules) {
      const slot = rule.slot ?? 1
      grouped.set(slot, [...(grouped.get(slot) ?? []), rule])
    }
    return grouped
  }, [slots, sortedRules])

  const filteredRolesForSlot = (slot: number) => {
    const q = (newRoleNameInputs[slot] ?? '').trim().toLowerCase()
    if (!q) return roles
    return roles.filter((r) => r.role_name.toLowerCase().includes(q))
  }

  const addRule = (slot: number) => {
    setError(null)
    setSaved(null)
    const newLevel = newLevels[slot] ?? 0
    const selectedRoleId = selectedRoleIds[slot] ?? ''
    if (!Number.isInteger(newLevel) || newLevel < 0) {
      setError('レベルは 0 以上の整数を指定してください。')
      return
    }
    if (!selectedRoleId) {
      setError('ドロップダウンからロールを選択してください。')
      return
    }
    const chosenRole = roles.find((r) => r.role_id === selectedRoleId)
    if (!chosenRole) {
      setError('選択可能なロールがありません。')
      return
    }
    if (rules.some((r) => r.slot === slot && r.level === newLevel)) {
      setError(`スロット ${slot} には同じレベルを重複設定できません。`)
      return
    }
    setRules((prev) => [
      ...prev,
      {
        slot,
        level: newLevel,
        role_id: chosenRole.role_id,
        role_name: chosenRole.role_name,
      },
    ])
    setNewRoleNameInputs((prev) => ({ ...prev, [slot]: '' }))
    setSelectedRoleIds((prev) => ({ ...prev, [slot]: '' }))
  }

  const removeSlot = (slot: number) => {
    if (slotCount <= 1) return
    setSaved(null)
    setRules((prev) => removeSlotAndReindex(prev, slot))
    setNewLevels((prev) => {
      const next: Record<number, number> = {}
      for (const [k, v] of Object.entries(prev)) {
        const key = Number(k)
        if (key === slot) continue
        next[key > slot ? key - 1 : key] = v
      }
      return next
    })
    setNewRoleNameInputs((prev) => {
      const next: Record<number, string> = {}
      for (const [k, v] of Object.entries(prev)) {
        const key = Number(k)
        if (key === slot) continue
        next[key > slot ? key - 1 : key] = v
      }
      return next
    })
    setSelectedRoleIds((prev) => {
      const next: Record<number, string> = {}
      for (const [k, v] of Object.entries(prev)) {
        const key = Number(k)
        if (key === slot) continue
        next[key > slot ? key - 1 : key] = v
      }
      return next
    })
    setSlotCount((prev) => Math.max(1, prev - 1))
  }

  const removeRule = (slot: number, level: number) => {
    setSaved(null)
    setRules((prev) => prev.filter((r) => !(r.slot === slot && r.level === level)))
  }

  const saveRules = () => {
    setError(null)
    setSaved(null)
    startTransition(async () => {
      const response = await fetch(`/api/v1/guilds/${guildId}/level-role-awards`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ rules: sortedRules }),
      })

      if (!response.ok) {
        const text = await response.text()
        try {
          const parsed = JSON.parse(text) as { detail?: string }
          setError(parsed.detail ?? '保存に失敗しました。')
        } catch {
          setError(text || '保存に失敗しました。')
        }
        return
      }

      const savedRules = (await response.json()) as Rule[]
      setRules(savedRules)
      setSlotCount((prev) =>
        Math.max(prev, 1, ...savedRules.map((rule) => rule.slot ?? 1)),
      )
      setSaved('保存しました。付与反映は通常20秒以内に開始されます。')
    })
  }

  return (
    <section className="rounded-xl border border-white/10 bg-white/[0.03] p-4">
      <h2 className="text-lg font-semibold">レベル到達ロール付与</h2>
      <p className="mt-1 text-sm text-white/60">
        管理画面からのみ設定できます。ロールは表示名で選択します。
      </p>

      <div className="mt-4">
        <button
          type="button"
          onClick={() => setSlotCount((prev) => prev + 1)}
          className="rounded-lg border border-white/20 bg-white/10 px-3 py-2 text-sm hover:bg-white/15"
        >
          スロット(パネル)を追加
        </button>
      </div>

      <div className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-2">
        {slots.map((slot) => {
          const datalistId = `role-name-list-${guildId}-${slot}`
          const slotRules = rulesBySlot.get(slot) ?? []
          const selectedRoleId = selectedRoleIds[slot] ?? ''
          return (
            <section
              key={slot}
              className="rounded-lg border border-white/10 bg-black/20 p-3"
            >
              <h3 className="text-sm font-semibold">スロット {slot}</h3>
              <div className="mt-2">
                <button
                  type="button"
                  disabled={slotCount <= 1}
                  onClick={() => removeSlot(slot)}
                  className="rounded-lg border border-red-300/30 bg-red-400/10 px-2 py-1 text-xs text-red-200 hover:bg-red-400/20 disabled:opacity-40"
                >
                  このスロットを削除
                </button>
              </div>
              <div className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-[120px_1fr_auto]">
                <input
                  type="number"
                  min={0}
                  value={newLevels[slot] ?? 0}
                  onChange={(e) =>
                    setNewLevels((prev) => ({
                      ...prev,
                      [slot]: Number(e.target.value || 0),
                    }))
                  }
                  className="rounded-lg border border-white/15 bg-black/20 px-3 py-2 text-sm"
                  placeholder="Level"
                />
                <input
                  list={datalistId}
                  value={newRoleNameInputs[slot] ?? ''}
                  onChange={(e) => {
                    const value = e.target.value
                    setNewRoleNameInputs((prev) => ({ ...prev, [slot]: value }))
                    const next = roles.find((r) =>
                      r.role_name.toLowerCase().includes(value.trim().toLowerCase()),
                    )
                    if (next) {
                      setSelectedRoleIds((prev) => ({ ...prev, [slot]: next.role_id }))
                    }
                  }}
                  className="rounded-lg border border-white/15 bg-black/20 px-3 py-2 text-sm"
                  placeholder="ロール名を入力 (候補あり)"
                />
                <select
                  value={selectedRoleId}
                  onChange={(e) =>
                    setSelectedRoleIds((prev) => ({
                      ...prev,
                      [slot]: e.target.value,
                    }))
                  }
                  className="rounded-lg border border-white/15 bg-black/20 px-3 py-2 text-sm"
                >
                  <option value="">候補から選択</option>
                  {filteredRolesForSlot(slot).map((role) => (
                    <option key={role.role_id} value={role.role_id}>
                      {role.role_name}
                    </option>
                  ))}
                </select>
                <datalist id={datalistId}>
                  {roles.map((role) => (
                    <option key={role.role_id} value={role.role_name} />
                  ))}
                </datalist>
                <button
                  type="button"
                  onClick={() => addRule(slot)}
                  className="rounded-lg border border-white/20 bg-white/10 px-3 py-2 text-sm hover:bg-white/15"
                >
                  追加
                </button>
              </div>
              <div className="mt-3 space-y-2">
                {slotRules.length === 0 ? (
                  <p className="text-sm text-white/50">このスロットの設定はまだありません。</p>
                ) : (
                  slotRules.map((rule) => (
                    <div
                      key={`${rule.slot}-${rule.level}`}
                      className="flex items-center justify-between rounded-lg border border-white/10 bg-black/20 px-3 py-2"
                    >
                      <span className="text-sm">
                        Lv {rule.level} → {rule.role_name}
                      </span>
                      <button
                        type="button"
                        onClick={() => removeRule(slot, rule.level)}
                        className="text-xs text-red-300 hover:text-red-200"
                      >
                        削除
                      </button>
                    </div>
                  ))
                )}
              </div>
            </section>
          )
        })}
      </div>

      <div className="mt-4 flex items-center gap-3">
        <button
          type="button"
          onClick={saveRules}
          disabled={pending}
          className="rounded-lg border border-emerald-400/40 bg-emerald-400/20 px-4 py-2 text-sm hover:bg-emerald-400/30 disabled:opacity-50"
        >
          {pending ? '保存中…' : '保存'}
        </button>
        {saved ? <p className="text-xs text-emerald-300">{saved}</p> : null}
        {error ? <p className="text-xs text-red-300">{error}</p> : null}
      </div>
    </section>
  )
}
