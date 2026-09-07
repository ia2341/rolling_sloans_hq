import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'

import type { Timeline } from '../../api/scheduleTypes'
import { RehearsalOverview } from './RehearsalOverview'

const timeline: Timeline = {
  slots: [
    {
      song_id: 1,
      song_title: 'First Song',
      start_time: '18:00:00',
      end_time: '19:00:00',
      is_viewer: true,
    },
  ],
  window_start: '18:00:00',
  window_end: '19:00:00',
  viewer_song_count: 1,
  total_song_count: 1,
  viewer_start_time: '18:00:00',
  viewer_end_time: '19:00:00',
  is_dress_rehearsal: false,
}

describe('RehearsalOverview', () => {
  it('shows the date sentence by default, with the dress qualifier when set', () => {
    render(
      <MemoryRouter>
        <RehearsalOverview
          heading="Next rehearsal"
          date="2026-03-10"
          isDress
          timeline={timeline}
        />
      </MemoryRouter>,
    )

    expect(screen.getByText(/10th March, Tuesday/)).toBeInTheDocument()
    expect(screen.getByText(/dress rehearsal/)).toBeInTheDocument()
  })

  it('omits the date sentence when showDate is false', () => {
    render(
      <MemoryRouter>
        <RehearsalOverview
          heading="You at this rehearsal"
          date="2026-03-10"
          isDress={false}
          timeline={timeline}
          showDate={false}
        />
      </MemoryRouter>,
    )

    expect(screen.queryByText(/10th March, Tuesday/)).not.toBeInTheDocument()
    expect(
      screen.getByRole('heading', { name: 'You at this rehearsal' }),
    ).toBeInTheDocument()
  })
})
