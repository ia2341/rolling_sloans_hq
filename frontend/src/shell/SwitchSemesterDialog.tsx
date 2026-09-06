import { Check } from 'lucide-react'

import { ResponsiveDialog } from '../components/ui/ResponsiveDialog'
import { useSemesterOptionItems } from './useSemesterOptionItems'

interface SwitchSemesterDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
}

/**
 * The phone More sheet's "Switch semester" destination (issue #329): the
 * same Semester list `SemesterPanel`'s Viewing dropdown shows, as a plain
 * `ResponsiveDialog` list rather than `ResponsiveMenu` — `ResponsiveMenu`
 * owns its own internal open state keyed to a trigger element, which
 * doesn't fit a menu opened by an already-closing sibling sheet. Selecting
 * an option closes this dialog.
 */
export function SwitchSemesterDialog({
  open,
  onOpenChange,
}: SwitchSemesterDialogProps) {
  const { items } = useSemesterOptionItems()

  return (
    <ResponsiveDialog open={open} onOpenChange={onOpenChange} title="Viewing">
      <ul className="flex flex-col">
        {items.map((item) => (
          <li key={item.key}>
            <button
              type="button"
              onClick={() => {
                item.onSelect()
                onOpenChange(false)
              }}
              className="flex w-full items-center gap-2 rounded px-2 py-2 text-left text-sm hover:bg-rs-border/40"
            >
              <span className="w-4 shrink-0">
                {item.selected && <Check size={14} aria-hidden="true" />}
              </span>
              <span className="flex flex-col">
                <span>{item.label}</span>
                {item.secondaryText !== undefined && (
                  <span className="text-xs text-rs-muted">
                    {item.secondaryText}
                  </span>
                )}
              </span>
            </button>
          </li>
        ))}
      </ul>
    </ResponsiveDialog>
  )
}
