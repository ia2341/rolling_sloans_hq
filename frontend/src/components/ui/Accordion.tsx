import * as RadixAccordion from '@radix-ui/react-accordion'
import { ChevronDown } from 'lucide-react'
import type { ReactNode } from 'react'

export interface AccordionItem {
  key: string
  /** The collapsed summary line, always visible. */
  summary: ReactNode
  content: ReactNode
  /** Optional controls rendered beside the summary, outside the Trigger so they don't nest inside its button. */
  actions?: ReactNode
}

interface AccordionProps {
  items: AccordionItem[]
  defaultOpenKey?: string
  /**
   * Controlled mode (issue #337): pass alongside `onOpenKeyChange` when a
   * caller needs to read or drive which row is open itself — e.g. to keep
   * the open row in sync with the URL so a round trip elsewhere re-opens
   * the same row. `''` means "nothing open". Omit both to keep the
   * original uncontrolled behaviour (`defaultOpenKey` only).
   */
  openKey?: string
  onOpenKeyChange?: (key: string) => void
}

/**
 * A single-open accordion (issue #328 user story 35): opening a row closes
 * whichever row was open. This is the default, not a per-surface decision
 * — it was chosen because a draft that gave every rehearsal a full-width
 * band made a six-rehearsal editor take several screens.
 */
export function Accordion({
  items,
  defaultOpenKey,
  openKey,
  onOpenKeyChange,
}: AccordionProps) {
  const controlledProps =
    openKey !== undefined
      ? { value: openKey, onValueChange: onOpenKeyChange }
      : { defaultValue: defaultOpenKey }

  return (
    <RadixAccordion.Root type="single" collapsible {...controlledProps}>
      {items.map((item) => (
        <RadixAccordion.Item
          key={item.key}
          value={item.key}
          className="border-b border-rs-border"
        >
          <RadixAccordion.Header className="flex items-center gap-2">
            <RadixAccordion.Trigger className="group flex flex-1 items-center justify-between gap-2 py-3 text-left">
              <span className="flex-1">{item.summary}</span>
              <ChevronDown
                size={16}
                aria-hidden="true"
                className="shrink-0 transition-transform group-data-[state=open]:rotate-180"
              />
            </RadixAccordion.Trigger>
            {item.actions}
          </RadixAccordion.Header>
          <RadixAccordion.Content className="pb-3">
            {item.content}
          </RadixAccordion.Content>
        </RadixAccordion.Item>
      ))}
    </RadixAccordion.Root>
  )
}
