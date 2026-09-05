import { useState } from 'react'

import { apiFetch } from '../../api/client'
import type { SpotifyImportCandidate, SpotifyImportPayload } from '../../api/setlistTypes'
import type { ReadEnvelope } from '../../api/types'
import { ResponsiveDialog } from '../../components/ui/ResponsiveDialog'
import { SegmentedControl } from '../../components/ui/SegmentedControl'
import type { EditRow } from './setlistEditModel'
import { nextRowKey } from './setlistEditModel'

type Source = 'spotify' | 'byhand'

interface AddSongsSheetProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  /** Appends staged rows to the same Pending Buffer a hand-edit fills -- nothing about them is special afterwards (issue #335, #310). */
  onAddRows: (rows: EditRow[]) => void
}

/**
 * The `+ Add songs` sheet (issue #335, #310): the *one* door new rows come
 * through. A modal on desktop and a bottom sheet on phone via
 * `ResponsiveDialog`, its two sources are sections behind a
 * `SegmentedControl` rather than three stacked forms. Nothing here writes
 * anything -- ticked Spotify candidates and a typed row both become
 * ordinary Buffer rows only once "Add to the buffer" is pressed, via
 * `onAddRows`; the real write is still the toolbar's Save changes ->
 * the shared Save popup (#334).
 */
export function AddSongsSheet({ open, onOpenChange, onAddRows }: AddSongsSheetProps) {
  const [source, setSource] = useState<Source>('spotify')

  const [playlistUrl, setPlaylistUrl] = useState('')
  const [fetching, setFetching] = useState(false)
  const [fetchMessage, setFetchMessage] = useState<string | null>(null)
  const [candidates, setCandidates] = useState<SpotifyImportCandidate[]>([])
  const [ticked, setTicked] = useState<Set<number>>(new Set())
  const [skippedNote, setSkippedNote] = useState('')

  const [handTitle, setHandTitle] = useState('')
  const [handArtist, setHandArtist] = useState('')
  const [handLength, setHandLength] = useState('')

  function resetAndClose() {
    setPlaylistUrl('')
    setFetching(false)
    setFetchMessage(null)
    setCandidates([])
    setTicked(new Set())
    setSkippedNote('')
    setHandTitle('')
    setHandArtist('')
    setHandLength('')
    onOpenChange(false)
  }

  function fetchPlaylist() {
    setFetching(true)
    setFetchMessage(null)
    void apiFetch<ReadEnvelope<SpotifyImportPayload>>('/api/setlist/spotify/', {
      method: 'POST',
      body: JSON.stringify({ url: playlistUrl }),
    }).then(
      (envelope) => {
        setFetching(false)
        if (envelope.data.message) {
          setFetchMessage(envelope.data.message)
          setCandidates([])
          setSkippedNote('')
          return
        }
        setCandidates(envelope.data.songs)
        setTicked(new Set())
        setSkippedNote(describeSkipped(envelope.data.skipped_count, envelope.data.skipped_reasons))
      },
      () => {
        setFetching(false)
        setFetchMessage("Couldn't reach Spotify; the import was not completed.")
      },
    )
  }

  function toggleTicked(index: number) {
    setTicked((current) => {
      const next = new Set(current)
      if (next.has(index)) next.delete(index)
      else next.add(index)
      return next
    })
  }

  function addToBuffer() {
    const rows: EditRow[] = []
    if (source === 'spotify') {
      candidates.forEach((candidate, index) => {
        if (!ticked.has(index)) return
        rows.push(newRow(candidate.title, candidate.artist, candidate.length, 'spotify'))
      })
    } else if (handTitle.trim()) {
      rows.push(newRow(handTitle, handArtist, handLength, 'byhand'))
    }
    if (rows.length > 0) onAddRows(rows)
    resetAndClose()
  }

  const canAdd =
    source === 'spotify' ? ticked.size > 0 : handTitle.trim() !== ''

  return (
    <ResponsiveDialog
      open={open}
      onOpenChange={(next) => {
        if (!next) resetAndClose()
        else onOpenChange(next)
      }}
      title="Add songs"
      wide
      footer={
        <>
          <button
            type="button"
            onClick={resetAndClose}
            className="rounded border border-rs-border px-3 py-1.5 text-sm font-medium hover:bg-rs-border/40"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={addToBuffer}
            disabled={!canAdd}
            className="rounded bg-rs-accent px-3 py-1.5 text-sm font-medium text-rs-accent-fg disabled:cursor-not-allowed disabled:opacity-50"
          >
            Add to the buffer
          </button>
        </>
      }
    >
      <SegmentedControl
        ariaLabel="Add songs from"
        options={[
          { value: 'spotify', label: 'From a Spotify playlist' },
          { value: 'byhand', label: 'By hand' },
        ]}
        value={source}
        onChange={(next) => setSource(next as Source)}
      />

      {source === 'spotify' ? (
        <div className="pt-3">
          <label className="text-sm" htmlFor="spotify-playlist-url">
            Playlist link
          </label>
          <div className="mt-1 flex gap-2">
            <input
              id="spotify-playlist-url"
              type="text"
              value={playlistUrl}
              onChange={(event) => setPlaylistUrl(event.target.value)}
              placeholder="https://open.spotify.com/playlist/..."
              className="flex-1 rounded border border-rs-border px-2 py-1 text-sm"
            />
            <button
              type="button"
              onClick={fetchPlaylist}
              disabled={fetching || playlistUrl.trim() === ''}
              className="rounded border border-rs-border px-3 py-1.5 text-sm font-medium disabled:cursor-not-allowed disabled:opacity-50"
            >
              {fetching ? 'Fetching…' : 'Fetch'}
            </button>
          </div>

          {fetchMessage && (
            <p role="alert" className="pt-3 text-sm text-rs-muted">
              {fetchMessage}
            </p>
          )}

          {skippedNote && <p className="pt-2 text-xs text-rs-muted">{skippedNote}</p>}

          {candidates.length > 0 && (
            <ul className="mt-3 max-h-64 space-y-1 overflow-y-auto">
              {candidates.map((candidate, index) => (
                <li key={`${candidate.title}-${index}`}>
                  <label
                    className={
                      candidate.already_in_setlist
                        ? 'flex items-center gap-2 rounded p-1.5 text-sm text-rs-muted'
                        : 'flex items-center gap-2 rounded p-1.5 text-sm'
                    }
                  >
                    <input
                      type="checkbox"
                      checked={ticked.has(index)}
                      onChange={() => toggleTicked(index)}
                    />
                    <span className="flex-1">
                      {candidate.title} · {candidate.artist} · {candidate.length}
                      {candidate.already_in_setlist && (
                        <span className="block text-xs italic">Already in this setlist</span>
                      )}
                    </span>
                  </label>
                </li>
              ))}
            </ul>
          )}
        </div>
      ) : (
        <div className="flex flex-col gap-2 pt-3">
          <div>
            <label className="text-sm" htmlFor="byhand-title">
              Title
            </label>
            <input
              id="byhand-title"
              type="text"
              value={handTitle}
              onChange={(event) => setHandTitle(event.target.value)}
              className="mt-1 block w-full rounded border border-rs-border px-2 py-1 text-sm"
            />
          </div>
          <div>
            <label className="text-sm" htmlFor="byhand-artist">
              Artist
            </label>
            <input
              id="byhand-artist"
              type="text"
              value={handArtist}
              onChange={(event) => setHandArtist(event.target.value)}
              className="mt-1 block w-full rounded border border-rs-border px-2 py-1 text-sm"
            />
          </div>
          <div>
            <label className="text-sm" htmlFor="byhand-length">
              Length (M:SS)
            </label>
            <input
              id="byhand-length"
              type="text"
              value={handLength}
              onChange={(event) => setHandLength(event.target.value)}
              placeholder="3:45"
              className="mt-1 block w-full rounded border border-rs-border px-2 py-1 text-sm"
            />
          </div>
        </div>
      )}
    </ResponsiveDialog>
  )
}

/** Builds one brand-new `EditRow` for the sheet's "Add to the buffer" action. */
function newRow(title: string, artist: string, length: string, origin: 'spotify' | 'byhand'): EditRow {
  return {
    rowKey: nextRowKey(origin),
    songId: null,
    title,
    artist,
    length,
    notes: '',
    deleted: false,
    origin,
    recordingCount: 0,
    original: null,
    originalPosition: null,
  }
}

/** Builds the "Skipped N items (...)" note from a fetch's skip counts, or `''` when nothing was skipped. */
function describeSkipped(skippedCount: number, skippedReasons: Record<string, number>): string {
  if (skippedCount === 0) return ''
  const parts = Object.entries(skippedReasons).map(
    ([reason, count]) => `${count} ${reason}${count === 1 ? '' : 's'}`,
  )
  return `Skipped ${skippedCount} item${skippedCount === 1 ? '' : 's'} (${parts.join(', ')})`
}
