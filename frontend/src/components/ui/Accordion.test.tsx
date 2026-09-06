import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import { Accordion } from './Accordion'

describe('Accordion', () => {
  it('opens one row at a time', async () => {
    const user = userEvent.setup()
    render(
      <Accordion
        items={[
          {
            key: 'mon',
            summary: 'Monday rehearsal',
            content: 'Monday details',
          },
          {
            key: 'wed',
            summary: 'Wednesday rehearsal',
            content: 'Wednesday details',
          },
        ]}
      />,
    )

    expect(screen.queryByText('Monday details')).not.toBeInTheDocument()
    expect(screen.queryByText('Wednesday details')).not.toBeInTheDocument()

    await user.click(screen.getByText('Monday rehearsal'))
    expect(screen.getByText('Monday details')).toBeVisible()
    expect(screen.queryByText('Wednesday details')).not.toBeInTheDocument()

    await user.click(screen.getByText('Wednesday rehearsal'))
    expect(screen.queryByText('Monday details')).not.toBeInTheDocument()
    expect(screen.getByText('Wednesday details')).toBeVisible()
  })
})
