import { describe, expect, it } from 'vitest'

import type { SetlistSong } from '../../api/setlistTypes'
import {
  buildBufferWire,
  computeChangeCount,
  mapSetlistPreviewToResult,
  moveAliveRow,
  rowBadges,
  rowsFromPayload,
  type EditRow,
  type SetlistWriteEnvelope,
} from './setlistEditModel'

function song(overrides: Partial<SetlistSong> = {}): SetlistSong {
  return {
    id: 1,
    title: 'Song A',
    artist: 'Artist A',
    length: '3:00',
    position: 1,
    notes: '',
    cast: [],
    recording_count: 0,
    ...overrides,
  }
}

function existingRow(overrides: Partial<EditRow> = {}): EditRow {
  return {
    rowKey: 'song-1',
    songId: 1,
    title: 'Song A',
    artist: 'Artist A',
    length: '3:00',
    notes: '',
    deleted: false,
    origin: 'existing',
    recordingCount: 0,
    original: { title: 'Song A', artist: 'Artist A', length: '3:00', notes: '' },
    originalPosition: 1,
    ...overrides,
  }
}

function newRow(overrides: Partial<EditRow> = {}): EditRow {
  return {
    rowKey: 'byhand-1',
    songId: null,
    title: 'New Song',
    artist: 'New Artist',
    length: '2:00',
    notes: '',
    deleted: false,
    origin: 'byhand',
    recordingCount: 0,
    original: null,
    originalPosition: null,
    ...overrides,
  }
}

describe('rowsFromPayload', () => {
  it('maps each song into an existing EditRow with its snapshot preserved', () => {
    const rows = rowsFromPayload([song({ id: 5, title: 'X', position: 2 })])
    expect(rows).toEqual([
      {
        rowKey: 'song-5',
        songId: 5,
        title: 'X',
        artist: 'Artist A',
        length: '3:00',
        notes: '',
        deleted: false,
        origin: 'existing',
        recordingCount: 0,
        original: { title: 'X', artist: 'Artist A', length: '3:00', notes: '' },
        originalPosition: 2,
      },
    ])
  })
})

describe('rowBadges', () => {
  it('returns ["Deleted"] for a deleted row regardless of other state', () => {
    const row = existingRow({ deleted: true, title: 'Changed' })
    expect(rowBadges(row, 0)).toEqual(['Deleted'])
  })

  it('returns ["New"] for a brand-new by-hand row', () => {
    const row = newRow({ origin: 'byhand' })
    expect(rowBadges(row, 0)).toEqual(['New'])
  })

  it('returns ["New · from Spotify"] for a brand-new Spotify row', () => {
    const row = newRow({ origin: 'spotify' })
    expect(rowBadges(row, 0)).toEqual(['New · from Spotify'])
  })

  it('returns no badges for an untouched existing row at its original position', () => {
    const row = existingRow({ originalPosition: 1 })
    expect(rowBadges(row, 0)).toEqual([])
  })

  it('returns a Moved badge when the alive index differs from originalPosition', () => {
    const row = existingRow({ originalPosition: 3 })
    expect(rowBadges(row, 0)).toEqual(['Moved 3→1'])
  })

  it('returns both Moved and Edited badges when both apply', () => {
    const row = existingRow({ originalPosition: 3, title: 'Changed' })
    expect(rowBadges(row, 0)).toEqual(['Moved 3→1', 'Edited'])
  })
})

describe('moveAliveRow', () => {
  it('swaps a row with the next alive row when moving down', () => {
    const rows = [existingRow({ rowKey: 'a' }), existingRow({ rowKey: 'b' })]
    const result = moveAliveRow(rows, 'a', 1)
    expect(result.map((row) => row.rowKey)).toEqual(['b', 'a'])
  })

  it('swaps a row with the previous alive row when moving up', () => {
    const rows = [existingRow({ rowKey: 'a' }), existingRow({ rowKey: 'b' })]
    const result = moveAliveRow(rows, 'b', -1)
    expect(result.map((row) => row.rowKey)).toEqual(['b', 'a'])
  })

  it('skips over deleted rows rather than swapping with them', () => {
    const rows = [
      existingRow({ rowKey: 'a' }),
      existingRow({ rowKey: 'b', deleted: true }),
      existingRow({ rowKey: 'c' }),
    ]
    const result = moveAliveRow(rows, 'a', 1)
    expect(result.map((row) => row.rowKey)).toEqual(['c', 'b', 'a'])
  })

  it('returns rows unchanged when there is nowhere to move', () => {
    const rows = [existingRow({ rowKey: 'a' }), existingRow({ rowKey: 'b' })]
    const result = moveAliveRow(rows, 'a', -1)
    expect(result).toBe(rows)
  })
})

describe('computeChangeCount', () => {
  it('returns 0 for an unmodified buffer', () => {
    const rows = [existingRow()]
    expect(computeChangeCount(rows)).toBe(0)
  })

  it('counts a brand-new row as one change', () => {
    const rows = [existingRow(), newRow()]
    expect(computeChangeCount(rows)).toBe(1)
  })

  it('counts an edited existing row as one change', () => {
    const rows = [existingRow({ title: 'Changed' })]
    expect(computeChangeCount(rows)).toBe(1)
  })

  it('counts a deleted row as one change even though it stays in the array', () => {
    const rows = [existingRow({ deleted: true })]
    expect(computeChangeCount(rows)).toBe(1)
  })

  it('counts a whole-buffer reorder as exactly one change regardless of how many rows moved', () => {
    const rows = [
      existingRow({ rowKey: 'a', songId: 1, originalPosition: 2 }),
      existingRow({ rowKey: 'b', songId: 2, originalPosition: 1 }),
    ]
    expect(computeChangeCount(rows)).toBe(1)
  })
})

describe('buildBufferWire', () => {
  it('excludes deleted rows from rows and lists their songId under deleted_song_ids', () => {
    const rows = [
      existingRow({ rowKey: 'a', songId: 1 }),
      existingRow({ rowKey: 'b', songId: 2, deleted: true }),
    ]
    const wire = buildBufferWire(9, '2026-01-01T00:00:00Z', rows)
    expect(wire).toEqual({
      semester_id: 9,
      semester_updated_at: '2026-01-01T00:00:00Z',
      rows: [
        {
          row_key: 'a',
          song_id: 1,
          title: 'Song A',
          artist: 'Artist A',
          length: '3:00',
          notes: '',
        },
      ],
      deleted_song_ids: [2],
    })
  })

  it('omits a deleted brand-new row from deleted_song_ids since it was never saved', () => {
    const rows = [newRow({ rowKey: 'a', deleted: true })]
    const wire = buildBufferWire(9, '2026-01-01T00:00:00Z', rows)
    expect(wire.rows).toEqual([])
    expect(wire.deleted_song_ids).toEqual([])
  })
})

function baseEnvelope(overrides: Partial<SetlistWriteEnvelope> = {}): SetlistWriteEnvelope {
  return {
    context: {} as SetlistWriteEnvelope['context'],
    ok: true,
    errors: {},
    non_field_errors: [],
    fallout: {
      is_blocked: false,
      block_message: '',
      is_stale: false,
      pending_adds: [],
      pending_edits: [],
      reordered: false,
      pending_deletions: [],
      loud: [],
      quiet: [],
    },
    values: null,
    data: null,
    ...overrides,
  }
}

describe('mapSetlistPreviewToResult', () => {
  it('maps a validation failure (ok: false) to a not-ok PreviewResult with errors', () => {
    const envelope = baseEnvelope({
      ok: false,
      fallout: null,
      errors: { 'song-1': { title: ['Required'] } },
      non_field_errors: ['Something went wrong'],
    })
    const result = mapSetlistPreviewToResult(envelope)
    expect(result.ok).toBe(false)
    expect(result.errors).toEqual({ 'song-1': { title: ['Required'] } })
    expect(result.nonFieldErrors).toEqual(['Something went wrong'])
  })

  it('maps a stale semester to ok: false with the stale message', () => {
    const envelope = baseEnvelope({
      fallout: {
        is_blocked: false,
        block_message: '',
        is_stale: true,
        pending_adds: [],
        pending_edits: [],
        reordered: false,
        pending_deletions: [],
        loud: [],
        quiet: [],
      },
    })
    const result = mapSetlistPreviewToResult(envelope)
    expect(result.ok).toBe(false)
    expect(result.nonFieldErrors).toEqual([
      'The setlist changed while you were editing — reload and reapply.',
    ])
  })

  it('maps adds, edits, deletions and reorder into PreviewChanges', () => {
    const envelope = baseEnvelope({
      fallout: {
        is_blocked: false,
        block_message: '',
        is_stale: false,
        pending_adds: ['New Song'],
        pending_edits: ['Old Song: title changed'],
        reordered: true,
        pending_deletions: [
          { title: 'Gone Song', recording_count: 0, uploader_count: 0, running_order_count: 0 },
        ],
        loud: ['loud message'],
        quiet: ['quiet message'],
      },
    })
    const result = mapSetlistPreviewToResult(envelope)
    expect(result.ok).toBe(true)
    expect(result.changes).toEqual([
      { op: 'Add', object: 'New Song' },
      { op: 'Edit', object: 'Old Song: title changed' },
      { op: 'Delete', object: 'Gone Song' },
      { op: 'Move', object: 'Setlist order', why: 'concert position only' },
    ])
    expect(result.fallout).toEqual({ loud: ['loud message'], quiet: ['quiet message'] })
  })

  it('builds a doomed block only when a deletion carries recordings', () => {
    const envelope = baseEnvelope({
      fallout: {
        is_blocked: false,
        block_message: '',
        is_stale: false,
        pending_adds: [],
        pending_edits: [],
        reordered: false,
        pending_deletions: [
          { title: 'Recorded Song', recording_count: 3, uploader_count: 2, running_order_count: 0 },
        ],
        loud: [],
        quiet: [],
      },
    })
    const result = mapSetlistPreviewToResult(envelope)
    expect(result.doomed).toEqual({
      heading: '3 Recordings are destroyed by this save',
      items: ['Recorded Song — 3 takes from 2 uploaders'],
    })
  })

  it('omits the doomed block when no deletion carries any recordings', () => {
    const envelope = baseEnvelope({
      fallout: {
        is_blocked: false,
        block_message: '',
        is_stale: false,
        pending_adds: [],
        pending_edits: [],
        reordered: false,
        pending_deletions: [
          { title: 'Clean Song', recording_count: 0, uploader_count: 0, running_order_count: 0 },
        ],
        loud: [],
        quiet: [],
      },
    })
    const result = mapSetlistPreviewToResult(envelope)
    expect(result.doomed).toBeUndefined()
  })
})
