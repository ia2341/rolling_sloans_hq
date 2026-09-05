import * as Dialog from '@radix-ui/react-dialog'
import { X } from 'lucide-react'
import { useEffect, useRef, type ReactNode } from 'react'

import { useIsPhone } from '../../hooks/useIsPhone'
import { cn } from '../../lib/utils'

interface ResponsiveDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  title: string
  children: ReactNode
  /** Footer buttons, ordered dismiss then commit (issue #328). */
  footer?: ReactNode
  /** The wide variant used by grid-shaped dialogs (~520px vs. the ~560px default), per issue #328. */
  wide?: boolean
}

/**
 * The one dialog every surface in the SPA uses (issue #328 user stories
 * 31-32): a centred modal above the phone breakpoint, a bottom sheet below
 * it, from a single call site. Radix's `Dialog` supplies focus trapping,
 * Escape-to-close and backdrop dismissal for free. Focus return to the
 * trigger is handled here rather than by Radix's own mechanism: that only
 * fires for a `Dialog.Trigger` sub-component, and every call site here
 * manages its own trigger element outside this component (the six-part
 * `open`/`onOpenChange` contract has no trigger prop to wire one up), so
 * this tracks `document.activeElement` itself at the moment the dialog
 * opens and restores it on close.
 */
export function ResponsiveDialog({
  open,
  onOpenChange,
  title,
  children,
  footer,
  wide = false,
}: ResponsiveDialogProps) {
  const isPhone = useIsPhone()
  const previouslyFocused = useRef<HTMLElement | null>(null)

  useEffect(() => {
    if (open)
      previouslyFocused.current = document.activeElement as HTMLElement | null
  }, [open])

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-black/40" />
        <Dialog.Content
          onCloseAutoFocus={(event) => {
            event.preventDefault()
            previouslyFocused.current?.focus()
          }}
          className={cn(
            'fixed z-50 flex flex-col bg-rs-surface text-rs-fg shadow-lg focus:outline-none',
            isPhone
              ? 'inset-x-0 bottom-0 max-h-[85vh] rounded-t-xl'
              : cn(
                  'left-1/2 top-1/2 max-h-[85vh] w-[calc(100vw-2rem)] -translate-x-1/2 -translate-y-1/2 rounded-lg',
                  wide ? 'max-w-[520px]' : 'max-w-[560px]',
                ),
          )}
        >
          <div className="flex items-center justify-between border-b border-rs-border px-4 py-3">
            <Dialog.Title className="text-base font-semibold">
              {title}
            </Dialog.Title>
            <Dialog.Close
              aria-label="Close"
              className="rounded p-1 text-rs-muted hover:bg-rs-border/40 hover:text-rs-fg"
            >
              <X size={18} aria-hidden="true" />
            </Dialog.Close>
          </div>
          <div className="overflow-y-auto px-4 py-3">{children}</div>
          {footer !== undefined && (
            <div className="flex justify-end gap-2 border-t border-rs-border px-4 py-3">
              {footer}
            </div>
          )}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
