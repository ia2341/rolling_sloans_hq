import { useState } from 'react'

import type { RoleCountRow, RoleGroupOption } from './roleCountStepModel'
import {
  clampCount,
  defaultCountFor,
  visibleRoleGroups,
} from './roleCountStepModel'

export interface StagedSongRow {
  rowKey: string
  title: string
  artist: string
}

interface RoleCountStepTableProps {
  songs: StagedSongRow[]
  groups: RoleGroupOption[]
  counts: Record<string, RoleCountRow>
  addedGroupNames: Set<string>
  onChangeCount: (rowKey: string, groupName: string, next: number) => void
  onAddGroup: (groupName: string) => void
}

/**
 * The Add Songs popup's second step (issue #460): one row per staged
 * song, one column per Role Group with a nonzero default count or one
 * the admin explicitly revealed via "Add Role" -- an all-zero column,
 * including a named default stepped down to 0, is hidden. `counts` and
 * `addedGroupNames` are owned by `AddSongsSheet` (this step doesn't
 * outlive the popup, so there's nothing to lift further), leaving this
 * component the table markup and the stepper controls only.
 */
export function RoleCountStepTable({
  songs,
  groups,
  counts,
  addedGroupNames,
  onChangeCount,
  onAddGroup,
}: RoleCountStepTableProps) {
  const visible = visibleRoleGroups(groups, counts, addedGroupNames)
  const hidden = groups.filter(
    (group) => !visible.some((shown) => shown.name === group.name),
  )
  const [pendingAdd, setPendingAdd] = useState('')

  return (
    <div className="pt-3">
      <p className="pb-2 text-sm text-rs-muted">
        These counts can be changed later via each song&apos;s Requirements
        editor.
      </p>

      <div className="overflow-x-auto">
        <table className="w-full min-w-max border-collapse text-sm">
          <thead>
            <tr>
              <th className="border-b border-rs-border px-2 py-1 text-left font-medium">
                Song
              </th>
              {visible.map((group) => (
                <th
                  key={group.name}
                  className="border-b border-rs-border px-2 py-1 text-center font-medium"
                >
                  {group.name}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {songs.map((song) => (
              <tr key={song.rowKey}>
                <td className="border-b border-rs-border px-2 py-1">
                  {song.title || 'Untitled'}
                  {song.artist && (
                    <span className="text-rs-muted"> · {song.artist}</span>
                  )}
                </td>
                {visible.map((group) => {
                  const count = counts[song.rowKey]?.[group.name] ?? 0
                  return (
                    <td
                      key={group.name}
                      className="border-b border-rs-border px-2 py-1"
                    >
                      <div className="flex items-center justify-center gap-1.5">
                        <button
                          type="button"
                          aria-label={`Decrease ${group.name} for ${song.title || 'Untitled'}`}
                          onClick={() =>
                            onChangeCount(
                              song.rowKey,
                              group.name,
                              clampCount(count - 1),
                            )
                          }
                          disabled={count <= 0}
                          className="h-6 w-6 rounded border border-rs-border text-xs font-medium leading-none disabled:cursor-not-allowed disabled:opacity-40"
                        >
                          −
                        </button>
                        <span className="w-5 text-center tabular-nums">
                          {count}
                        </span>
                        <button
                          type="button"
                          aria-label={`Increase ${group.name} for ${song.title || 'Untitled'}`}
                          onClick={() =>
                            onChangeCount(
                              song.rowKey,
                              group.name,
                              clampCount(count + 1),
                            )
                          }
                          className="h-6 w-6 rounded border border-rs-border text-xs font-medium leading-none"
                        >
                          +
                        </button>
                      </div>
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {hidden.length > 0 && (
        <div className="mt-3 flex items-center gap-2">
          <label className="text-sm" htmlFor="add-role-group">
            Add Role
          </label>
          <select
            id="add-role-group"
            value={pendingAdd}
            onChange={(event) => {
              const name = event.target.value
              if (!name) return
              onAddGroup(name)
              setPendingAdd('')
            }}
            className="rounded border border-rs-border px-2 py-1 text-sm"
          >
            <option value="">Choose a Role Group…</option>
            {hidden.map((group) => (
              <option key={group.name} value={group.name}>
                {group.name} (default {defaultCountFor(group.name)})
              </option>
            ))}
          </select>
        </div>
      )}
    </div>
  )
}
