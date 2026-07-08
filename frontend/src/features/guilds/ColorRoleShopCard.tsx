'use client'

import { useMemo, useState, useTransition } from 'react'

interface RoleOption {
  role_id: string
  role_name: string
  position: number
  color: number
  is_managed: boolean
}

interface ChannelOption {
  channel_id: string
  channel_name: string
  channel_type: string
}

interface ColorRoleShopItem {
  id: number
  role_id: string
  role_name: string
  label: string
  description: string | null
  cost_xp: number
  color: number
}

interface Props {
  guildId: string
  roles: RoleOption[]
  channels: ChannelOption[]
  initialItems: ColorRoleShopItem[]
}

function parseErrorMessage(text: string): string {
  try {
    const parsed = JSON.parse(text) as { detail?: unknown }
    if (typeof parsed.detail === 'string') {
      return parsed.detail
    }
    if (parsed.detail !== undefined) {
      return JSON.stringify(parsed.detail)
    }
    return text
  } catch {
    return text
  }
}

function roleColorCss(color: number): string {
  const normalized = Math.max(0, Math.min(0xffffff, Math.trunc(color)))
  if (normalized <= 0) {
    return 'rgba(148, 163, 184, 0.55)'
  }
  return `#${normalized.toString(16).padStart(6, '0')}`
}

function normalizedDescription(value: string): string | null {
  return value.trim() || null
}

function digitsOnly(value: string): string {
  return value.replace(/[^0-9]/g, '')
}

function parseXpInput(value: string): number | null {
  if (!/^[0-9]+$/.test(value)) {
    return null
  }
  const parsed = Number(value)
  if (!Number.isSafeInteger(parsed) || parsed < 1) {
    return null
  }
  return parsed
}

export function ColorRoleShopCard({
  guildId,
  roles,
  channels,
  initialItems,
}: Props) {
  const [items, setItems] = useState<ColorRoleShopItem[]>(initialItems)
  const [roleNameInput, setRoleNameInput] = useState('')
  const [selectedRoleId, setSelectedRoleId] = useState('')
  const [costXp, setCostXp] = useState('100')
  const [description, setDescription] = useState('')
  const [editingRoleId, setEditingRoleId] = useState<string | null>(null)
  const [editingCostXp, setEditingCostXp] = useState('100')
  const [editingDescription, setEditingDescription] = useState('')
  const [panelChannelId, setPanelChannelId] = useState(channels[0]?.channel_id ?? '')
  const [message, setMessage] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [pending, startTransition] = useTransition()

  const filteredRoles = useMemo(() => {
    const q = roleNameInput.trim().toLowerCase()
    if (!q) return roles
    return roles.filter((role) => role.role_name.toLowerCase().includes(q))
  }, [roleNameInput, roles])

  const sortedItems = useMemo(
    () => [...items].sort((a, b) => a.cost_xp - b.cost_xp || a.id - b.id),
    [items],
  )

  const registeredRoleIds = useMemo(
    () => new Set(items.map((item) => item.role_id)),
    [items],
  )

  const selectedRole = roles.find((role) => role.role_id === selectedRoleId)

  const resetAddForm = () => {
    setRoleNameInput('')
    setSelectedRoleId('')
    setCostXp('100')
    setDescription('')
  }

  const addItem = () => {
    setError(null)
    setMessage(null)
    if (!selectedRoleId || !selectedRole) {
      setError('ロールを選択してください。')
      return
    }
    if (registeredRoleIds.has(selectedRoleId)) {
      setError('登録済みのロールです。下の一覧から編集してください。')
      return
    }
    const parsedCostXp = parseXpInput(costXp)
    if (parsedCostXp === null) {
      setError('必要XPは半角数字で 1 以上の整数を指定してください。')
      return
    }

    startTransition(async () => {
      const response = await fetch(
        `/api/v1/guilds/${guildId}/color-role-shop/items/${selectedRoleId}`,
        {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            role_id: selectedRoleId,
            cost_xp: parsedCostXp,
            description: normalizedDescription(description),
          }),
        },
      )

      if (!response.ok) {
        setError(parseErrorMessage(await response.text()) || '保存に失敗しました。')
        return
      }

      const saved = (await response.json()) as ColorRoleShopItem
      setItems((prev) => [
        ...prev.filter((item) => item.role_id !== saved.role_id),
        saved,
      ])
      resetAddForm()
      setMessage(`${saved.role_name} を追加しました。`)
    })
  }

  const startEditing = (item: ColorRoleShopItem) => {
    setError(null)
    setMessage(null)
    setEditingRoleId(item.role_id)
    setEditingCostXp(String(item.cost_xp))
    setEditingDescription(item.description ?? '')
  }

  const cancelEditing = () => {
    setEditingRoleId(null)
    setEditingCostXp('100')
    setEditingDescription('')
  }

  const updateItem = (item: ColorRoleShopItem) => {
    setError(null)
    setMessage(null)
    const parsedEditingCostXp = parseXpInput(editingCostXp)
    if (parsedEditingCostXp === null) {
      setError('必要XPは半角数字で 1 以上の整数を指定してください。')
      return
    }

    startTransition(async () => {
      const response = await fetch(
        `/api/v1/guilds/${guildId}/color-role-shop/items/${item.role_id}`,
        {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            role_id: item.role_id,
            cost_xp: parsedEditingCostXp,
            description: normalizedDescription(editingDescription),
          }),
        },
      )

      if (!response.ok) {
        setError(parseErrorMessage(await response.text()) || '更新に失敗しました。')
        return
      }

      const saved = (await response.json()) as ColorRoleShopItem
      setItems((prev) =>
        prev.map((candidate) =>
          candidate.role_id === saved.role_id ? saved : candidate,
        ),
      )
      cancelEditing()
      setMessage(`${saved.role_name} を更新しました。`)
    })
  }

  const deleteItem = (item: ColorRoleShopItem) => {
    setError(null)
    setMessage(null)
    if (!window.confirm(`${item.role_name} を交換対象から削除します。`)) {
      return
    }

    startTransition(async () => {
      const response = await fetch(
        `/api/v1/guilds/${guildId}/color-role-shop/items/${item.role_id}`,
        { method: 'DELETE' },
      )

      if (!response.ok) {
        setError(parseErrorMessage(await response.text()) || '削除に失敗しました。')
        return
      }

      setItems((prev) =>
        prev.filter((candidate) => candidate.role_id !== item.role_id),
      )
      if (editingRoleId === item.role_id) {
        cancelEditing()
      }
      setMessage(`${item.role_name} を削除しました。`)
    })
  }

  const postPanel = () => {
    setError(null)
    setMessage(null)
    if (!panelChannelId) {
      setError('投稿先チャンネルを選択してください。')
      return
    }

    startTransition(async () => {
      const response = await fetch(
        `/api/v1/guilds/${guildId}/color-role-shop/panel`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ channel_id: panelChannelId }),
        },
      )

      if (!response.ok) {
        setError(parseErrorMessage(await response.text()) || '投稿に失敗しました。')
        return
      }

      const posted = (await response.json()) as { message_id: string }
      setMessage(`パネルを投稿しました。ID: ${posted.message_id}`)
    })
  }

  return (
    <section className="rounded-xl border border-white/10 bg-white/[0.03] p-4">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <h2 className="text-lg font-semibold">カラーロール交換所</h2>
          <p className="mt-1 text-sm text-white/60">
            交換対象 {items.length} 件 / 投稿先 {channels.length} 件
          </p>
        </div>
        <div className="flex flex-col gap-2 sm:flex-row">
          <select
            value={panelChannelId}
            onChange={(e) => setPanelChannelId(e.target.value)}
            className="rounded-lg border border-white/15 bg-black/20 px-3 py-2 text-sm"
          >
            <option value="">投稿先チャンネル</option>
            {channels.map((channel) => (
              <option key={channel.channel_id} value={channel.channel_id}>
                #{channel.channel_name}
              </option>
            ))}
          </select>
          <button
            type="button"
            onClick={postPanel}
            disabled={pending || channels.length === 0}
            className="rounded-lg border border-sky-300/40 bg-sky-400/20 px-4 py-2 text-sm hover:bg-sky-400/30 disabled:opacity-50"
          >
            パネル投稿
          </button>
        </div>
      </div>

      <div className="mt-4 border-t border-white/10 pt-4">
        <h3 className="text-sm font-semibold">交換対象を追加</h3>
        <div className="mt-3 grid grid-cols-1 gap-2 xl:grid-cols-[1fr_1fr_120px_1fr_auto]">
          <input
            list={`color-role-list-${guildId}`}
            value={roleNameInput}
            onChange={(e) => {
              const value = e.target.value
              setRoleNameInput(value)
              const next = roles.find(
                (role) =>
                  role.role_name.toLowerCase() === value.trim().toLowerCase(),
              )
              setSelectedRoleId(next?.role_id ?? '')
            }}
            className="rounded-lg border border-white/15 bg-black/20 px-3 py-2 text-sm"
            placeholder="ロール名を入力"
          />
          <select
            value={selectedRoleId}
            onChange={(e) => {
              const roleId = e.target.value
              setSelectedRoleId(roleId)
              const next = roles.find((role) => role.role_id === roleId)
              setRoleNameInput(next?.role_name ?? '')
            }}
            className="rounded-lg border border-white/15 bg-black/20 px-3 py-2 text-sm"
          >
            <option value="">候補から選択</option>
            {filteredRoles.map((role) => (
              <option
                key={role.role_id}
                value={role.role_id}
                disabled={registeredRoleIds.has(role.role_id)}
              >
                {role.role_name}
                {registeredRoleIds.has(role.role_id) ? '（登録済み）' : ''}
              </option>
            ))}
          </select>
          <input
            type="text"
            inputMode="numeric"
            pattern="[0-9]*"
            value={costXp}
            onChange={(e) => setCostXp(digitsOnly(e.target.value))}
            className="rounded-lg border border-white/15 bg-black/20 px-3 py-2 text-sm"
            placeholder="必要XP"
          />
          <input
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            className="rounded-lg border border-white/15 bg-black/20 px-3 py-2 text-sm"
            placeholder="説明"
            maxLength={160}
          />
          <datalist id={`color-role-list-${guildId}`}>
            {roles.map((role) => (
              <option key={role.role_id} value={role.role_name} />
            ))}
          </datalist>
          <button
            type="button"
            onClick={addItem}
            disabled={pending}
            className="rounded-lg border border-emerald-400/40 bg-emerald-400/20 px-4 py-2 text-sm hover:bg-emerald-400/30 disabled:opacity-50"
          >
            {pending ? '処理中…' : '追加'}
          </button>
        </div>
      </div>

      <div className="mt-4 space-y-2">
        {sortedItems.length === 0 ? (
          <p className="text-sm text-white/50">交換対象はまだありません。</p>
        ) : (
          sortedItems.map((item) => (
            <div
              key={item.id}
              className="rounded-lg border border-white/10 bg-black/20 px-3 py-2"
            >
              {editingRoleId === item.role_id ? (
                <div className="grid grid-cols-1 gap-2 lg:grid-cols-[1fr_120px_1fr_auto] lg:items-center">
                  <div className="flex min-w-0 items-center gap-2">
                    <span
                      aria-hidden="true"
                      className="h-4 w-4 shrink-0 rounded-full border border-white/15"
                      style={{ backgroundColor: roleColorCss(item.color) }}
                    />
                    <span className="truncate text-sm font-medium">
                      {item.role_name}
                    </span>
                  </div>
                  <input
                    type="text"
                    inputMode="numeric"
                    pattern="[0-9]*"
                    value={editingCostXp}
                    onChange={(e) => setEditingCostXp(digitsOnly(e.target.value))}
                    className="rounded-lg border border-white/15 bg-black/20 px-3 py-2 text-sm"
                    placeholder="必要XP"
                  />
                  <input
                    value={editingDescription}
                    onChange={(e) => setEditingDescription(e.target.value)}
                    className="rounded-lg border border-white/15 bg-black/20 px-3 py-2 text-sm"
                    placeholder="説明"
                    maxLength={160}
                  />
                  <div className="flex gap-2">
                    <button
                      type="button"
                      onClick={() => updateItem(item)}
                      disabled={pending}
                      className="rounded-lg border border-emerald-400/40 bg-emerald-400/20 px-3 py-2 text-sm hover:bg-emerald-400/30 disabled:opacity-50"
                    >
                      保存
                    </button>
                    <button
                      type="button"
                      onClick={cancelEditing}
                      disabled={pending}
                      className="rounded-lg border border-white/15 bg-white/5 px-3 py-2 text-sm text-white/70 hover:bg-white/10 disabled:opacity-50"
                    >
                      キャンセル
                    </button>
                  </div>
                </div>
              ) : (
                <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                  <div className="flex min-w-0 items-start gap-3">
                    <span
                      aria-hidden="true"
                      className="mt-0.5 h-4 w-4 shrink-0 rounded-full border border-white/15"
                      style={{ backgroundColor: roleColorCss(item.color) }}
                    />
                    <div className="min-w-0">
                      <div className="truncate text-sm font-medium">
                        {item.role_name} · {item.cost_xp.toLocaleString()} XP
                      </div>
                      {item.description ? (
                        <div className="truncate text-xs text-white/50">
                          {item.description}
                        </div>
                      ) : null}
                    </div>
                  </div>
                  <div className="flex gap-3 text-xs">
                    <button
                      type="button"
                      onClick={() => startEditing(item)}
                      disabled={pending}
                      className="text-sky-200 hover:text-sky-100 disabled:opacity-50"
                    >
                      編集
                    </button>
                    <button
                      type="button"
                      onClick={() => deleteItem(item)}
                      disabled={pending}
                      className="text-red-300 hover:text-red-200 disabled:opacity-50"
                    >
                      削除
                    </button>
                  </div>
                </div>
              )}
            </div>
          ))
        )}
      </div>

      <div className="mt-4 min-h-4">
        {message ? <p className="text-xs text-emerald-300">{message}</p> : null}
        {error ? <p className="text-xs text-red-300">{error}</p> : null}
      </div>
    </section>
  )
}
