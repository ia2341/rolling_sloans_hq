import * as DropdownMenu from '@radix-ui/react-dropdown-menu'
import { Check } from 'lucide-react'
import {
  cloneElement,
  isValidElement,
  useState,
  type ReactElement,
} from 'react'

import { useIsPhone } from '../../hooks/useIsPhone'
import { ResponsiveDialog } from './ResponsiveDialog'

export interface ResponsiveMenuItem {
  key: string
  label: string
  secondaryText?: string
  selected?: boolean
  onSelect: () => void
}

interface ResponsiveMenuProps {
  trigger: ReactElement
  /** The caption row above the items (a desktop `DropdownMenu.Label`, the phone sheet's title). */
  caption: string
  items: ResponsiveMenuItem[]
}

/**
 * An anchored dropdown menu on desktop, a bottom sheet on a phone (issue
 * #328) — the Viewing dropdown (#329) is its first consumer. Selectable
 * items carry a tick when `selected`, plus optional secondary text.
 */
export function ResponsiveMenu({
  trigger,
  caption,
  items,
}: ResponsiveMenuProps) {
  const isPhone = useIsPhone()
  const [open, setOpen] = useState(false)

  if (isPhone) {
    const triggerWithHandler = isValidElement<{ onClick?: () => void }>(trigger)
      ? cloneElement(trigger, { onClick: () => setOpen(true) })
      : trigger

    return (
      <>
        {triggerWithHandler}
        <ResponsiveDialog open={open} onOpenChange={setOpen} title={caption}>
          <ul className="flex flex-col">
            {items.map((item) => (
              <li key={item.key}>
                <button
                  type="button"
                  onClick={() => {
                    item.onSelect()
                    setOpen(false)
                  }}
                  className="flex w-full items-center gap-2 rounded px-2 py-2 text-left text-sm hover:bg-rs-border/40"
                >
                  <MenuItemContent item={item} />
                </button>
              </li>
            ))}
          </ul>
        </ResponsiveDialog>
      </>
    )
  }

  return (
    <DropdownMenu.Root open={open} onOpenChange={setOpen}>
      <DropdownMenu.Trigger asChild>{trigger}</DropdownMenu.Trigger>
      <DropdownMenu.Portal>
        <DropdownMenu.Content
          align="start"
          sideOffset={4}
          className="z-50 min-w-56 rounded-md border border-rs-border bg-rs-surface py-1 shadow-lg"
        >
          <DropdownMenu.Label className="px-3 py-1.5 text-xs font-medium uppercase tracking-wide text-rs-muted">
            {caption}
          </DropdownMenu.Label>
          {items.map((item) => (
            <DropdownMenu.Item
              key={item.key}
              onSelect={item.onSelect}
              className="flex cursor-pointer items-center gap-2 px-3 py-2 text-sm outline-none data-[highlighted]:bg-rs-border/40"
            >
              <MenuItemContent item={item} />
            </DropdownMenu.Item>
          ))}
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  )
}

/** The tick, label and secondary text shared by a menu item's desktop-dropdown and phone-sheet rendering. */
function MenuItemContent({ item }: { item: ResponsiveMenuItem }) {
  return (
    <>
      <span className="w-4 shrink-0">
        {item.selected && <Check size={14} aria-hidden="true" />}
      </span>
      <span className="flex flex-col">
        <span>{item.label}</span>
        {item.secondaryText !== undefined && (
          <span className="text-xs text-rs-muted">{item.secondaryText}</span>
        )}
      </span>
    </>
  )
}
