import { useState } from 'react'

import { apiFetch } from '../../api/client'
import type {
  SpotifyImportCandidate,
  SpotifyImportPayload,
} from '../../api/setlistTypes'
import type { ReadEnvelope } from '../../api/types'
import { Accordion } from '../../components/ui/Accordion'
import { ResponsiveDialog } from '../../components/ui/ResponsiveDialog'
import { SegmentedControl } from '../../components/ui/SegmentedControl'
import type { EditRow } from './setlistEditModel'
import { nextRowKey } from './setlistEditModel'

type Source = 'spotify' | 'byhand'

interface HandCard {
  key: string
  title: string
  artist: string
  length: string
}

/** Builds one empty, freshly-keyed by-hand card for the Accordion. */
function newHandCard(): HandCard {
  return { key: nextRowKey('byhand-card'), title: '', artist: '', length: '' }
}

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
 * anything -- ticked Spotify candidates and one or more typed by-hand cards
 * (issue #458, staged via the single-open `Accordion`) both become ordinary
 * Buffer rows only once the source's confirm button is pressed, via
 * `onAddRows`; the real write is still the toolbar's Save changes ->
 * the shared Save popup (#334).
 */
export function AddSongsSheet({
  open,
  onOpenChange,
  onAddRows,
}: AddSongsSheetProps) {
  const [source, setSource] = useState<Source>('spotify')

  const [playlistUrl, setPlaylistUrl] = useState('')
  const [fetching, setFetching] = useState(false)
  const [fetchMessage, setFetchMessage] = useState<string | null>(null)
  const [candidates, setCandidates] = useState<SpotifyImportCandidate[]>([])
  const [ticked, setTicked] = useState<Set<number>>(new Set())
  const [skippedNote, setSkippedNote] = useState('')

  const [handCards, setHandCards] = useState<HandCard[]>(() => [newHandCard()])
  const [openHandCardKey, setOpenHandCardKey] = useState(
    () => handCards[0]?.key ?? '',
  )

  function resetAndClose() {
    setPlaylistUrl('')
    setFetching(false)
    setFetchMessage(null)
    setCandidates([])
    setTicked(new Set())
    setSkippedNote('')
    const firstCard = newHandCard()
    setHandCards([firstCard])
    setOpenHandCardKey(firstCard.key)
    onOpenChange(false)
  }

  /** Edits one field of one staged by-hand card by key. */
  function updateHandCard(
    key: string,
    field: keyof Omit<HandCard, 'key'>,
    value: string,
  ) {
    setHandCards((cards) =>
      cards.map((card) =>
        card.key === key ? { ...card, [field]: value } : card,
      ),
    )
  }

  /** Stages a new empty card, collapsing the rest by opening only this one. */
  function addAnotherHandCard() {
    const card = newHandCard()
    setHandCards((cards) => [...cards, card])
    setOpenHandCardKey(card.key)
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
        setSkippedNote(
          describeSkipped(
            envelope.data.skipped_count,
            envelope.data.skipped_reasons,
          ),
        )
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
        rows.push(
          newRow(
            candidate.title,
            candidate.artist,
            candidate.length,
            'spotify',
          ),
        )
      })
    } else {
      handCards.forEach((card) => {
        if (!card.title.trim()) return
        rows.push(newRow(card.title, card.artist, card.length, 'byhand'))
      })
    }
    if (rows.length > 0) onAddRows(rows)
    resetAndClose()
  }

  const canAdd =
    source === 'spotify'
      ? ticked.size > 0
      : handCards.some((card) => card.title.trim() !== '')

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
          {source === 'byhand' && (
            <button
              type="button"
              onClick={addAnotherHandCard}
              className="rounded border border-rs-border px-3 py-1.5 text-sm font-medium hover:bg-rs-border/40"
            >
              Add Another Song
            </button>
          )}
          <button
            type="button"
            onClick={addToBuffer}
            disabled={!canAdd}
            className="rounded bg-rs-accent px-3 py-1.5 text-sm font-medium text-rs-accent-fg disabled:cursor-not-allowed disabled:opacity-50"
          >
            {source === 'byhand' ? 'Confirm Songs' : 'Add to the buffer'}
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

          {skippedNote && (
            <p className="pt-2 text-xs text-rs-muted">{skippedNote}</p>
          )}

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
                      {candidate.title} · {candidate.artist} ·{' '}
                      {candidate.length}
                      {candidate.already_in_setlist && (
                        <span className="block text-xs italic">
                          Already in this setlist
                        </span>
                      )}
                    </span>
                  </label>
                </li>
              ))}
            </ul>
          )}
        </div>
      ) : (
        <div className="pt-3">
          <Accordion
            openKey={openHandCardKey}
            onOpenKeyChange={setOpenHandCardKey}
            items={handCards.map((card, index) => ({
              key: card.key,
              summary: handCardSummary(card, index),
              content: (
                <div className="flex flex-col gap-2">
                  <div>
                    <label
                      className="text-sm"
                      htmlFor={`byhand-title-${card.key}`}
                    >
                      Title
                    </label>
                    <input
                      id={`byhand-title-${card.key}`}
                      type="text"
                      value={card.title}
                      onChange={(event) =>
                        updateHandCard(card.key, 'title', event.target.value)
                      }
                      className="mt-1 block w-full rounded border border-rs-border px-2 py-1 text-sm"
                    />
                  </div>
                  <div>
                    <label
                      className="text-sm"
                      htmlFor={`byhand-artist-${card.key}`}
                    >
                      Artist
                    </label>
                    <input
                      id={`byhand-artist-${card.key}`}
                      type="text"
                      value={card.artist}
                      onChange={(event) =>
                        updateHandCard(card.key, 'artist', event.target.value)
                      }
                      className="mt-1 block w-full rounded border border-rs-border px-2 py-1 text-sm"
                    />
                  </div>
                  <div>
                    <label
                      className="text-sm"
                      htmlFor={`byhand-length-${card.key}`}
                    >
                      Length (M:SS)
                    </label>
                    <input
                      id={`byhand-length-${card.key}`}
                      type="text"
                      value={card.length}
                      onChange={(event) =>
                        updateHandCard(card.key, 'length', event.target.value)
                      }
                      placeholder="3:45"
                      className="mt-1 block w-full rounded border border-rs-border px-2 py-1 text-sm"
                    />
                  </div>
                </div>
              ),
            }))}
          />
        </div>
      )}
    </ResponsiveDialog>
  )
}

/** Collapsed-trigger summary for a by-hand card, so a collapsed card still identifies which song it holds. */
function handCardSummary(card: HandCard, index: number): string {
  if (!card.title.trim()) return `Song ${index + 1}`
  return card.artist.trim() ? `${card.title} · ${card.artist}` : card.title
}

/** Builds one brand-new `EditRow` for the sheet's confirm action, whichever source it came from. */
function newRow(
  title: string,
  artist: string,
  length: string,
  origin: 'spotify' | 'byhand',
): EditRow {
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
function describeSkipped(
  skippedCount: number,
  skippedReasons: Record<string, number>,
): string {
  if (skippedCount === 0) return ''
  const parts = Object.entries(skippedReasons).map(
    ([reason, count]) => `${count} ${reason}${count === 1 ? '' : 's'}`,
  )
  return `Skipped ${skippedCount} item${skippedCount === 1 ? '' : 's'} (${parts.join(', ')})`
}
