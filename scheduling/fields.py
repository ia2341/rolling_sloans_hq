"""Form fields for the scheduling domain.

Holds `SongLengthField`, the `M:SS` reader/writer for `Song.length` (issue
#177). It lives beside the forms rather than inside them because it is a
parser with a round-trip contract that outlives the admin screen it is
first wired into: the setlist edit grid and the Spotify playlist import
both reuse it (spec #172).
"""

import re
from datetime import timedelta

from django import forms
from django.core.exceptions import ValidationError

#: `M:SS` / `MM:SS` — leading minutes unbounded (a rendered `75:00` must parse back).
_MINUTES_SECONDS = re.compile(r'^(\d+):([0-5]\d)$')

#: `H:MM:SS` — minutes and seconds are clock fields here, so both are capped at 59.
_HOURS_MINUTES_SECONDS = re.compile(r'^(\d+):([0-5]\d):([0-5]\d)$')

#: Upper bound on a song's running time. Nothing near it is a real value; past it, a typo.
MAX_SONG_LENGTH = timedelta(hours=24)

INVALID_MESSAGE = 'Enter a length as M:SS (e.g. 3:45) or H:MM:SS (e.g. 1:15:00).'
OUT_OF_RANGE_MESSAGE = 'Enter a length longer than 0:00 and under 24 hours.'


def format_song_length(value):
    """Render a duration the way a musician says it: `3:45`, `4:05`, `12:05`, `75:00`.

    Minutes are unpadded (so they read as two digits only from ten minutes
    up) and seconds are always zero-padded. An hour-plus duration renders
    in minutes — `75:00`, not `1:15:00` — which is correct under the rule
    and irrelevant in practice. Sub-second precision (as Spotify's
    milliseconds supply) is truncated, not rounded.

    `None` renders as the empty string. Anything else — notably the raw
    string an admin typed into a bound form that failed validation — is
    handed back untouched, so a re-rendered form still shows what they
    typed.
    """
    if value is None:
        return ''
    if not isinstance(value, timedelta):
        return value
    total_seconds = int(value.total_seconds())
    minutes, seconds = divmod(total_seconds, 60)
    return f'{minutes}:{seconds:02d}'


def parse_song_length(value):
    """Parse `M:SS`, `MM:SS` or `H:MM:SS` into a `timedelta`, the way a musician means it.

    `3:45` is three minutes forty-five seconds, never three hours
    forty-five minutes. A colon-less number is rejected rather than guessed
    at, as are a rolled-over seconds field (`3:60`), a negative value, and a
    duration of zero or 24 hours and over.

    Raises `ValidationError` on anything it cannot parse; never coerces
    silently.
    """
    text = str(value).strip()
    match = _MINUTES_SECONDS.match(text)
    if match:
        duration = timedelta(minutes=int(match.group(1)), seconds=int(match.group(2)))
    else:
        match = _HOURS_MINUTES_SECONDS.match(text)
        if not match:
            raise ValidationError(INVALID_MESSAGE, code='invalid')
        duration = timedelta(
            hours=int(match.group(1)), minutes=int(match.group(2)), seconds=int(match.group(3))
        )
    _validate_range(duration)
    return duration


def _validate_range(duration):
    """Reject a zero-or-shorter duration, or one at/over `MAX_SONG_LENGTH`, as out of range."""
    if duration <= timedelta(0) or duration >= MAX_SONG_LENGTH:
        raise ValidationError(OUT_OF_RANGE_MESSAGE, code='out_of_range')


class SongLengthWidget(forms.TextInput):
    """A text box that renders a stored `timedelta` back as `M:SS`."""

    def format_value(self, value):
        """Render a `timedelta` as `M:SS`, passing a raw typed string through unchanged."""
        return format_song_length(value)


class SongLengthField(forms.Field):
    """A `Song.length` form field that reads and writes `M:SS`.

    Deliberately a plain `Field`, not a `DurationField` subclass: Django's
    `DurationField` parses `3:45` as three hours forty-five minutes, so
    inheriting its `to_python` would leave the very bug this replaces one
    `super()` call away.
    """

    widget = SongLengthWidget

    def to_python(self, value):
        """Return `None` for an empty value, a `timedelta` unchanged, and otherwise the parse of `M:SS`/`H:MM:SS`."""
        if value in self.empty_values:
            return None
        if isinstance(value, timedelta):
            _validate_range(value)
            return value
        return parse_song_length(value)
