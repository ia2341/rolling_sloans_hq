import * as RadixAccordion from '@radix-ui/react-accordion'
import { ChevronDown } from 'lucide-react'
import type { ReactNode } from 'react'

export interface AccordionItem {
  key: string
  /** The collapsed summary line, always visible. */
  summary: ReactNode
  content: ReactNode
}

interface AccordionProps {
  items: AccordionItem[]
  defaultOpenKey?: string
}

/**
 * A single-open accordion (issue #328 user story 35): opening a row closes
 * whichever row was open. This is the default, not a per-surface decision
 * — it was chosen because a draft that gave every rehearsal a full-width
 * band made a six-rehearsal editor take several screens.
 */
export function Accordion({ items, defaultOpenKey }: AccordionProps) {
  return (
    <RadixAccordion.Root
      type="single"
      collapsible
      defaultValue={defaultOpenKey}
    >
      {items.map((item) => (
        <RadixAccordion.Item
          key={item.key}
          value={item.key}
          className="border-b border-rs-border"
        >
          <RadixAccordion.Header>
            <RadixAccordion.Trigger className="group flex w-full items-center justify-between gap-2 py-3 text-left">
              <span className="flex-1">{item.summary}</span>
              <ChevronDown
                size={16}
                aria-hidden="true"
                className="shrink-0 transition-transform group-data-[state=open]:rotate-180"
              />
            </RadixAccordion.Trigger>
          </RadixAccordion.Header>
          <RadixAccordion.Content className="pb-3">
            {item.content}
          </RadixAccordion.Content>
        </RadixAccordion.Item>
      ))}
    </RadixAccordion.Root>
  )
}
