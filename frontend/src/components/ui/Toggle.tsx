interface ToggleProps {
  pressed: boolean
  onPressedChange: (pressed: boolean) => void
  label: string
}

/**
 * A labelled on/off switch whose own markup states its condition (issue
 * #332): `aria-pressed` carries the boolean for a screen reader, and a
 * sliding knob carries it visually, so a filtered list can never be
 * misread as the unfiltered one from the control alone.
 */
export function Toggle({ pressed, onPressedChange, label }: ToggleProps) {
  return (
    <button
      type="button"
      aria-pressed={pressed}
      onClick={() => onPressedChange(!pressed)}
      className={`relative inline-flex h-6 w-11 shrink-0 items-center rounded-full transition-colors ${
        pressed ? 'bg-rs-accent' : 'bg-rs-border'
      }`}
    >
      <span className="sr-only">{label}</span>
      <span
        aria-hidden="true"
        className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
          pressed ? 'translate-x-6' : 'translate-x-1'
        }`}
      />
    </button>
  )
}
