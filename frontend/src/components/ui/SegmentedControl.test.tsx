import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { SegmentedControl } from './SegmentedControl'

describe('SegmentedControl', () => {
  it("exposes an accessible group label and reads the disabled half's reason as a title", () => {
    render(
      <SegmentedControl
        ariaLabel="Rehearsal scope"
        value="this"
        onChange={() => {}}
        options={[
          { value: 'this', label: 'This rehearsal' },
          {
            value: 'all',
            label: 'All rehearsals',
            disabledReason: 'The Dress Rehearsal has no assignments to edit.',
          },
        ]}
      />,
    )

    expect(
      screen.getByRole('radiogroup', { name: 'Rehearsal scope' }),
    ).toBeInTheDocument()
    const disabledOption = screen.getByRole('radio', { name: 'All rehearsals' })
    expect(disabledOption).toBeDisabled()
    expect(disabledOption).toHaveAttribute(
      'title',
      'The Dress Rehearsal has no assignments to edit.',
    )
  })

  it('goes full width via the max-phone: variant', () => {
    render(
      <SegmentedControl
        ariaLabel="Mode"
        value="a"
        onChange={() => {}}
        options={[
          { value: 'a', label: 'A' },
          { value: 'b', label: 'B' },
        ]}
      />,
    )

    expect(screen.getByRole('radiogroup', { name: 'Mode' })).toHaveClass(
      'max-phone:w-full',
    )
  })
})
