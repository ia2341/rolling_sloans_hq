import { LogOut, Repeat, Settings, SquarePlus, User } from 'lucide-react'
import { useNavigate } from 'react-router-dom'

import { useAppContext } from '../api/ContextProvider'
import { ResponsiveDialog } from '../components/ui/ResponsiveDialog'

interface MoreSheetProps {
  open: boolean
  onOpenChange: (open: boolean) => void
}

/**
 * The phone tab bar's fifth destination (issue #328 user stories 29-30): a
 * sheet holding the destinations with no tab. An admin gets the three
 * semester items (deliberately separate entries, not one door onto a menu
 * of doors) plus Profile and Log out; a member gets Profile and Log out.
 * The semester items are wired by #329 — this component owns the sheet
 * and the slot.
 */
export function MoreSheet({ open, onOpenChange }: MoreSheetProps) {
  const appContext = useAppContext()
  const navigate = useNavigate()
  const isAdmin = appContext?.viewer.is_admin ?? false

  const goTo = (path: string) => {
    onOpenChange(false)
    navigate(path)
  }

  return (
    <ResponsiveDialog open={open} onOpenChange={onOpenChange} title="More">
      <ul className="flex flex-col divide-y divide-rs-border">
        {isAdmin && (
          <>
            <MoreSheetItem
              icon={Repeat}
              label="Switch semester"
              secondaryText={
                appContext?.viewing_semester
                  ? `Editing ${appContext.viewing_semester.name}`
                  : undefined
              }
              onClick={() => {
                /* Wired by #329. */
              }}
            />
            <MoreSheetItem
              icon={SquarePlus}
              label="New semester"
              secondaryText="Names it and switches you to it"
              onClick={() => {
                /* Wired by #329. */
              }}
            />
            <MoreSheetItem
              icon={Settings}
              label="Manage semesters"
              secondaryText="Publish, reapply defaults, delete"
              onClick={() => {
                /* Wired by #329. */
              }}
            />
          </>
        )}
        <MoreSheetItem
          icon={User}
          label="Profile"
          onClick={() => goTo('/profile')}
        />
        <MoreSheetLogoutItem />
      </ul>
    </ResponsiveDialog>
  )
}

/** One row in the More sheet: an icon, a label, and optional secondary text. */
function MoreSheetItem({
  icon: Icon,
  label,
  secondaryText,
  onClick,
}: {
  icon: typeof User
  label: string
  secondaryText?: string
  onClick: () => void
}) {
  return (
    <li>
      <button
        type="button"
        onClick={onClick}
        className="flex w-full items-center gap-3 px-1 py-3 text-left"
      >
        <Icon size={18} aria-hidden="true" className="shrink-0 text-rs-muted" />
        <span className="flex flex-col">
          <span className="text-sm font-medium">{label}</span>
          {secondaryText !== undefined && (
            <span className="text-xs text-rs-muted">{secondaryText}</span>
          )}
        </span>
      </button>
    </li>
  )
}

/** The More sheet's Log out row: the same CSRF-carrying POST form as the sidebar's. */
function MoreSheetLogoutItem() {
  const match = document.cookie.match(/(?:^|; )csrftoken=([^;]*)/)
  const token = match ? decodeURIComponent(match[1] ?? '') : ''

  return (
    <li>
      <form action="/accounts/logout/" method="post" className="contents">
        <input type="hidden" name="csrfmiddlewaretoken" value={token} />
        <button
          type="submit"
          className="flex w-full items-center gap-3 px-1 py-3 text-left"
        >
          <LogOut
            size={18}
            aria-hidden="true"
            className="shrink-0 text-rs-muted"
          />
          <span className="text-sm font-medium">Log out</span>
        </button>
      </form>
    </li>
  )
}
