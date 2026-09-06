import {
  useRegisterEditSession,
  type EditSession,
} from '../shell/EditSessionContext'

/** Registers a fixed `EditSession` for the duration of the test, from inside the provider tree. */
export function RegisterTestEditSession(props: Partial<EditSession>) {
  useRegisterEditSession({
    what: 'the setlist',
    changeCount: 0,
    blockedReason: null,
    discard: () => {},
    requestSave: () => {},
    ...props,
  })
  return null
}
