import * as ToggleGroup from '@radix-ui/react-toggle-group'

import { cn } from '../../lib/utils'

export interface SegmentedControlOption {
  value: string
  label: string
  /** Disables this option; the reason renders as its `title` (issue #328 user story 34). */
  disabledReason?: string
}

interface SegmentedControlProps {
  ariaLabel: string
  options: SegmentedControlOption[]
  value: string
  onChange: (value: string) => void
}

/**
 * A labelled two-or-three-way mode switch (issue #328 user stories 33-34):
 * `aria-label` is required so it reads as a mode switch rather than a set
 * of links, arrow-key movement comes from Radix's `ToggleGroup`, and it
 * goes full width below the phone breakpoint via Tailwind's `phone:`
 * variant rather than a `useIsPhone()` branch, so it never needs
 * JavaScript to lay out correctly.
 */
export function SegmentedControl({
  ariaLabel,
  options,
  value,
  onChange,
}: SegmentedControlProps) {
  return (
    <ToggleGroup.Root
      type="single"
      aria-label={ariaLabel}
      value={value}
      onValueChange={(next) => {
        if (next) onChange(next)
      }}
      className="inline-flex w-auto max-phone:w-full rounded-md border border-rs-border p-0.5"
    >
      {options.map((option) => (
        <ToggleGroup.Item
          key={option.value}
          value={option.value}
          disabled={option.disabledReason !== undefined}
          title={option.disabledReason}
          className={cn(
            'flex-1 rounded px-3 py-1.5 text-sm font-medium text-rs-fg',
            'data-[state=on]:bg-rs-accent data-[state=on]:text-rs-accent-fg',
            'disabled:cursor-not-allowed disabled:opacity-50',
          )}
        >
          {option.label}
        </ToggleGroup.Item>
      ))}
    </ToggleGroup.Root>
  )
}
