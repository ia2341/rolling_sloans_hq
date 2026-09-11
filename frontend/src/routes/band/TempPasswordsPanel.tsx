import { useState } from 'react'

import type { RosterTempPasswordEntry } from '../../api/memberTypes'
import { ResponsiveDialog } from '../../components/ui/ResponsiveDialog'

interface TempPasswordsPanelProps {
  entries: RosterTempPasswordEntry[]
  onDismiss: () => void
}

/**
 * The post-Save reveal panel (issue #482, ADR 0018): the one place this
 * project ever shows a real, usable password, and it's shown exactly
 * once — `RosterSaveApiView` never returns it again, and this panel keeps
 * nothing in any persistent store. Relaying it is the admin's job (out
 * loud, or by text); this only has to make copying and reading each one
 * easy and be unmistakable that it won't come back once dismissed.
 */
export function TempPasswordsPanel({
  entries,
  onDismiss,
}: TempPasswordsPanelProps) {
  return (
    <ResponsiveDialog
      open={entries.length > 0}
      onOpenChange={(next) => {
        if (!next) onDismiss()
      }}
      title={`New temp password${entries.length === 1 ? '' : 's'}`}
      footer={
        <button
          type="button"
          onClick={onDismiss}
          className="rounded bg-rs-accent px-3 py-1.5 text-sm font-medium text-rs-accent-fg"
        >
          Done — I've relayed these
        </button>
      }
    >
      <p role="alert" className="mb-3 text-sm text-rs-danger">
        Shown once. Relay each password to its member now — it will not be shown
        again.
      </p>
      <ul className="flex flex-col gap-2">
        {entries.map((entry) => (
          <TempPasswordRow key={entry.email} entry={entry} />
        ))}
      </ul>
    </ResponsiveDialog>
  )
}

function TempPasswordRow({ entry }: { entry: RosterTempPasswordEntry }) {
  const [copied, setCopied] = useState(false)

  async function copy() {
    try {
      await navigator.clipboard.writeText(entry.temp_password)
      setCopied(true)
    } catch {
      setCopied(false)
    }
  }

  return (
    <li className="flex items-center justify-between gap-3 rounded border border-rs-border p-2">
      <div className="min-w-0">
        <p className="truncate text-sm font-medium">{entry.email}</p>
        <p className="font-mono text-sm tracking-wide">{entry.temp_password}</p>
      </div>
      <button
        type="button"
        onClick={() => void copy()}
        className="shrink-0 rounded border border-rs-border px-2 py-1 text-xs font-medium"
      >
        {copied ? 'Copied' : 'Copy'}
      </button>
    </li>
  )
}
