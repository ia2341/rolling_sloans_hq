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

  it("sizes slots by their own start/end within the window, so arrival/departure ticks land at the edges of the viewer's song block rather than drifting into the setup/teardown dead space", () => {
    const gracedTimeline: Timeline = {
      slots: [
        {
          song_id: 1,
          song_title: 'A',
          start_time: '11:10:00',
          end_time: '11:47:00',
          is_viewer: false,
        },
        {
          song_id: 2,
          song_title: 'B',
          start_time: '11:47:00',
          end_time: '12:23:00',
          is_viewer: false,
        },
        {
          song_id: 3,
          song_title: 'C',
          start_time: '12:23:00',
          end_time: '13:00:00',
          is_viewer: false,
        },
        {
          song_id: 4,
          song_title: 'D',
          start_time: '13:00:00',
          end_time: '13:36:00',
          is_viewer: false,
        },
        {
          song_id: 5,
          song_title: 'Kickstart My Heart',
          start_time: '13:36:00',
          end_time: '14:13:00',
          is_viewer: true,
        },
        {
          song_id: 6,
          song_title: 'F',
          start_time: '14:13:00',
          end_time: '14:50:00',
          is_viewer: false,
        },
      ],
      window_start: '11:00:00',
      window_end: '15:00:00',
      viewer_song_count: 1,
      total_song_count: 6,
      viewer_start_time: '13:31:00',
      viewer_end_time: '14:18:00',
      is_dress_rehearsal: false,
    }

    render(
      <MemoryRouter>
        <RehearsalOverview
          heading="Next rehearsal"
          date="2026-09-27"
          isDress={false}
          timeline={gracedTimeline}
        />
      </MemoryRouter>,
    )

    // The song runs 13:36-14:13 inside an 11:00-15:00 (240-minute) window,
    // so its slot should be sized to its own 37-minute span, not an equal
    // 1/6th share of the bar.
    const viewerSlot = screen.getByRole('link', { name: 'Kickstart My Heart' })
    const slotWidthPercent = parseFloat(viewerSlot.style.width)
    expect(slotWidthPercent).toBeCloseTo((37 / 240) * 100, 1)

    // Confirm dead-space blocks exist for setup (11:00-11:10) and
    // teardown (14:50-15:00) grace at the bar's edges.
    const timelineBar = screen.getByTestId('next-rehearsal-timeline')
    const deadSpaceBlocks = timelineBar.querySelectorAll(
      '[aria-hidden="true"].bg-rs-border\\/10',
    )
    expect(deadSpaceBlocks).toHaveLength(2)
  })
})
