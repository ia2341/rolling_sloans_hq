/**
 * The generic, surface-agnostic Preview result shape (issue #334).
 *
 * Every admin edit surface (#335-#340) previews by running the real save
 * and rolling it back (ADR 0008) and reports its Fallout through this one
 * shape — a client-side TypeScript type mirroring each surface's own
 * server-side Buffer/Fallout dataclasses is fine and expected, but it is
 * explicitly non-authoritative: only the server function's own output is
 * ever acted on here. `SaveChangesDialog` knows nothing about any one
 * surface's Buffer; it only ever renders a `PreviewResult`.
 */
export interface PreviewChange {
  /** A short verb token naming the kind of change, rendered as a badge. */
  op: 'Re-time' | 'Remove' | 'Add' | 'Delete' | 'Move' | 'Edit' | 'Invite' | 'Roles' | 'Rename'
  /** The thing the change applies to (a Song title, a Person's name, a Rehearsal's date, ...). */
  object: string
  /** An optional, quieter explanation of why this change happens. */
  why?: string
}

export interface PreviewFallout {
  /** Fallout that needs the admin's attention before they'd want to save, but never blocks saving. */
  loud: string[]
  /** Fallout that's simply true as a consequence, worth showing but not worth calling out. */
  quiet: string[]
}

/** The escalation block shown only when a Preview would destroy something with no undo (e.g. Recordings). */
export interface PreviewDoomed {
  heading: string
  items: string[]
}

/**
 * What a surface's `preview()` call resolves to. `ok: false` means the
 * submitted Buffer failed validation — `errors`/`nonFieldErrors` carry
 * why, and `changes`/`fallout` should be treated as absent even if
 * present, since they were never actually computed by the server for the
 * confirm button to make good on.
 */
export interface PreviewResult {
  ok: boolean
  changes: PreviewChange[]
  fallout: PreviewFallout
  /** Present only when saving would destroy something with no undo and no export. */
  doomed?: PreviewDoomed
  errors?: Record<string, Record<string, string[]>>
  nonFieldErrors?: string[]
}
