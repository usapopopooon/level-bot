'use client'

import { useMemo, useState, useTransition } from 'react'

interface RoleOption {
  role_id: string
  role_name: string
  position: number
  is_managed: boolean
}

interface Rule {
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
  const [newLevel, setNewLevel] = useState<number>(0)
  const [newRoleNameInput, setNewRoleNameInput] = useState<string>('')
  const [selectedRoleId, setSelectedRoleId] = useState<string>('')
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState<string | null>(null)
  const [pending, startTransition] = useTransition()

  const datalistId = `role-name-list-${guildId}`
  const filteredRoles = useMemo(() => {
    const q = newRoleNameInput.trim().toLowerCase()
    if (!q) return roles
    return roles.filter((r) => r.role_name.toLowerCase().includes(q))
  }, [roles, newRoleNameInput])

  const sortedRules = useMemo(
    () => [...rules].sort((a, b) => a.level - b.level),
    [rules],
  )

  const addRule = () => {
    setError(null)
    setSaved(null)
    const roleName = newRoleNameInput.trim()
    if (!Number.isInteger(newLevel) || newLevel < 0) {
      setError('レベルは 0 以上の整数を指定してください。')
      return
    }
    if (!roleName) {
      setError('ロール名を入力してください。')
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
    if (rules.some((r) => r.level === newLevel)) {
      setError('同じレベルの設定は 1 つだけです。')
      return
    }
    setRules((prev) => [
      ...prev,
      {
        level: newLevel,
        role_id: chosenRole.role_id,
        role_name: chosenRole.role_name,
      },
    ])
    setNewRoleNameInput('')
    setSelectedRoleId('')
  }

  const removeRule = (level: number) => {
    setSaved(null)
    setRules((prev) => prev.filter((r) => r.level !== level))
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
      setSaved('保存しました。')
    })
  }

  return (
    <section className="rounded-xl border border-white/10 bg-white/[0.03] p-4">
      <h2 className="text-lg font-semibold">レベル到達ロール付与</h2>
      <p className="mt-1 text-sm text-white/60">
        管理画面からのみ設定できます。ロールは表示名で選択します。
      </p>

      <div className="mt-4 grid grid-cols-1 gap-2 sm:grid-cols-[120px_1fr_auto]">
        <input
          type="number"
          min={0}
          value={newLevel}
          onChange={(e) => setNewLevel(Number(e.target.value || 0))}
          className="rounded-lg border border-white/15 bg-black/20 px-3 py-2 text-sm"
          placeholder="Level"
        />
        <input
          list={datalistId}
          value={newRoleNameInput}
          onChange={(e) => {
            const value = e.target.value
            setNewRoleNameInput(value)
            const next = roles.find((r) =>
              r.role_name.toLowerCase().includes(value.trim().toLowerCase()),
            )
            if (next) setSelectedRoleId(next.role_id)
          }}
          className="rounded-lg border border-white/15 bg-black/20 px-3 py-2 text-sm"
          placeholder="ロール名を入力 (候補あり)"
        />
        <select
          value={selectedRoleId}
          onChange={(e) => setSelectedRoleId(e.target.value)}
          className="rounded-lg border border-white/15 bg-black/20 px-3 py-2 text-sm"
        >
          <option value="">候補から選択</option>
          {filteredRoles.map((role) => (
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
          onClick={addRule}
          className="rounded-lg border border-white/20 bg-white/10 px-3 py-2 text-sm hover:bg-white/15"
        >
          追加
        </button>
      </div>

      <div className="mt-4 space-y-2">
        {sortedRules.length === 0 ? (
          <p className="text-sm text-white/50">設定はまだありません。</p>
        ) : (
          sortedRules.map((rule) => (
            <div
              key={rule.level}
              className="flex items-center justify-between rounded-lg border border-white/10 bg-black/20 px-3 py-2"
            >
              <span className="text-sm">
                Lv {rule.level} → {rule.role_name}
              </span>
              <button
                type="button"
                onClick={() => removeRule(rule.level)}
                className="text-xs text-red-300 hover:text-red-200"
              >
                削除
              </button>
            </div>
          ))
        )}
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
