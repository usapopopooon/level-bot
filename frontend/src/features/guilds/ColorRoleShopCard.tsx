'use client'

import { useMemo, useState, useTransition } from 'react'

interface RoleOption {
  role_id: string
  role_name: string
  position: number
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

export function ColorRoleShopCard({
  guildId,
  roles,
  channels,
  initialItems,
}: Props) {
  const [items, setItems] = useState<ColorRoleShopItem[]>(initialItems)
  const [roleNameInput, setRoleNameInput] = useState('')
  const [selectedRoleId, setSelectedRoleId] = useState('')
  const [costXp, setCostXp] = useState(100)
  const [description, setDescription] = useState('')
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

  const selectedRole = roles.find((role) => role.role_id === selectedRoleId)

  const saveItem = () => {
    setError(null)
    setMessage(null)
    if (!selectedRoleId || !selectedRole) {
      setError('ロールを選択してください。')
      return
    }
    if (!Number.isInteger(costXp) || costXp < 1) {
      setError('必要XPは 1 以上の整数を指定してください。')
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
            cost_xp: costXp,
            description: description.trim() || null,
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
      setRoleNameInput('')
      setSelectedRoleId('')
      setCostXp(100)
      setDescription('')
      setMessage(`${saved.role_name} を保存しました。`)
    })
  }

  const removeItem = (roleId: string) => {
    setError(null)
    setMessage(null)
    startTransition(async () => {
      const response = await fetch(
        `/api/v1/guilds/${guildId}/color-role-shop/items/${roleId}`,
        { method: 'DELETE' },
      )

      if (!response.ok) {
        setError(parseErrorMessage(await response.text()) || '無効化に失敗しました。')
        return
      }

      setItems((prev) => prev.filter((item) => item.role_id !== roleId))
      setMessage('交換対象から外しました。')
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

      <div className="mt-4 grid grid-cols-1 gap-2 lg:grid-cols-[1fr_120px_1fr_auto]">
        <input
          list={`color-role-list-${guildId}`}
          value={roleNameInput}
          onChange={(e) => {
            const value = e.target.value
            setRoleNameInput(value)
            const next = roles.find((role) =>
              role.role_name.toLowerCase().includes(value.trim().toLowerCase()),
            )
            if (next) {
              setSelectedRoleId(next.role_id)
            }
          }}
          className="rounded-lg border border-white/15 bg-black/20 px-3 py-2 text-sm"
          placeholder="ロール名を入力"
        />
        <input
          type="number"
          min={1}
          value={costXp}
          onChange={(e) => setCostXp(Number(e.target.value || 0))}
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
        <datalist id={`color-role-list-${guildId}`}>
          {roles.map((role) => (
            <option key={role.role_id} value={role.role_name} />
          ))}
        </datalist>
        <button
          type="button"
          onClick={saveItem}
          disabled={pending}
          className="rounded-lg border border-emerald-400/40 bg-emerald-400/20 px-4 py-2 text-sm hover:bg-emerald-400/30 disabled:opacity-50 lg:col-start-4"
        >
          {pending ? '処理中…' : '保存'}
        </button>
      </div>

      <div className="mt-4 space-y-2">
        {sortedItems.length === 0 ? (
          <p className="text-sm text-white/50">交換対象はまだありません。</p>
        ) : (
          sortedItems.map((item) => (
            <div
              key={item.id}
              className="flex flex-col gap-2 rounded-lg border border-white/10 bg-black/20 px-3 py-2 sm:flex-row sm:items-center sm:justify-between"
            >
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
              <button
                type="button"
                onClick={() => removeItem(item.role_id)}
                disabled={pending}
                className="w-fit text-xs text-red-300 hover:text-red-200 disabled:opacity-50"
              >
                無効化
              </button>
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
