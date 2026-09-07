import { describe, expect, it } from 'vitest'

import type { MatrixRow, RehearsalDetail } from '../../api/scheduleTypes'
import { buildAssignmentPicker } from './assignmentPicker'

const GUITAR_ROLE_ID = 5

function detailFor(overrides: {
  rows?: MatrixRow[]
  roster?: RehearsalDetail['roster']
  conflicted_person_ids?: number[]
}): Pick<RehearsalDetail, 'rows' | 'roster' | 'conflicted_person_ids'> {
  return {
    rows: overrides.rows ?? [
      {
        song_id: 100,
        song_title: 'Song One',
        song_artist: '',
        song_position: 1,
        song_length: '3:00',
        start_time: '19:00:00',
        rehearsal_song_id: 200,
        cells: [{ role_id: GUITAR_ROLE_ID, entries: [] }],
      },
    ],
    roster: overrides.roster ?? [
      { person_id: 1, person_name: 'Ada', declared_role_ids: [GUITAR_ROLE_ID] },
      { person_id: 2, person_name: 'Bea', declared_role_ids: [] },
    ],
    conflicted_person_ids: overrides.conflicted_person_ids ?? [],
  }
}

const CELL = {
  songId: 100,
  songTitle: 'Song One',
  roleId: GUITAR_ROLE_ID,
  roleName: 'Guitar',
}

describe('buildAssignmentPicker', () => {
  it('splits the roster into declared (this cell’s Role) and others', () => {
    const payload = buildAssignmentPicker(detailFor({}), CELL)

    expect(payload.declared.map((option) => option.person_name)).toEqual([
      'Ada',
    ])
    expect(payload.others.map((option) => option.person_name)).toEqual(['Bea'])
  })

  it('excludes a roster member already holding this exact (Song, Role) assignment', () => {
    const detail = detailFor({
      rows: [
        {
          song_id: 100,
          song_title: 'Song One',
          song_artist: '',
          song_position: 1,
          song_length: '3:00',
          start_time: '19:00:00',
          rehearsal_song_id: 200,
          cells: [
            {
              role_id: GUITAR_ROLE_ID,
              entries: [
                {
                  id: 9,
                  kind: 'assignment',
                  person_id: 1,
                  person_name: 'Ada',
                  is_role_mismatch: false,
                  has_conflict: false,
                },
              ],
            },
          ],
        },
      ],
    })

    const payload = buildAssignmentPicker(detail, CELL)

    expect(payload.declared).toEqual([])
    expect(payload.others.map((option) => option.person_name)).toEqual(['Bea'])
  })

  it('excludes a roster member already backed-up on this cell from the backup lists only', () => {
    const detail = detailFor({
      rows: [
        {
          song_id: 100,
          song_title: 'Song One',
          song_artist: '',
          song_position: 1,
          song_length: '3:00',
          start_time: '19:00:00',
          rehearsal_song_id: 200,
          cells: [
            {
              role_id: GUITAR_ROLE_ID,
              entries: [
                {
                  id: 9,
                  kind: 'backup',
                  person_id: 1,
                  person_name: 'Ada',
                  is_role_mismatch: false,
                  has_conflict: false,
                },
              ],
            },
          ],
        },
      ],
    })

    const payload = buildAssignmentPicker(detail, CELL)

    expect(payload.declared.map((option) => option.person_name)).toEqual([
      'Ada',
    ])
    expect(payload.backup_declared).toEqual([])
  })

  it('leaves both backup lists empty on the Dress Rehearsal (no RehearsalSong to anchor a Backup on, ADR 0006)', () => {
    const detail = detailFor({
      rows: [
        {
          song_id: 100,
          song_title: 'Song One',
          song_artist: '',
          song_position: 1,
          song_length: '3:00',
          start_time: null,
          rehearsal_song_id: null,
          cells: [{ role_id: GUITAR_ROLE_ID, entries: [] }],
        },
      ],
    })

    const payload = buildAssignmentPicker(detail, CELL)

    expect(payload.rehearsal_song_id).toBeNull()
    expect(payload.backup_declared).toEqual([])
    expect(payload.backup_others).toEqual([])
  })

  it('marks has_conflict from conflicted_person_ids', () => {
    const payload = buildAssignmentPicker(
      detailFor({ conflicted_person_ids: [2] }),
      CELL,
    )

    const bea = payload.others.find((option) => option.person_name === 'Bea')
    expect(bea?.has_conflict).toBe(true)
    const ada = payload.declared.find((option) => option.person_name === 'Ada')
    expect(ada?.has_conflict).toBe(false)
  })

  it('carries the cell’s song/role identity through to the payload', () => {
    const payload = buildAssignmentPicker(detailFor({}), CELL)

    expect(payload.song_id).toBe(100)
    expect(payload.song_title).toBe('Song One')
    expect(payload.role_id).toBe(GUITAR_ROLE_ID)
    expect(payload.role_name).toBe('Guitar')
  })
})
