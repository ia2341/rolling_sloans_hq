"""The M:SS Song-length form field: parsing, rendering, round-tripping and rejection (issue #177)."""

from datetime import timedelta

from django.core.exceptions import ValidationError
from django.test import TestCase

from scheduling.factories import SemesterFactory, SongFactory
from scheduling.fields import SongLengthField, format_song_length
from scheduling.forms import SongForm
from scheduling.models import Song


class FormatSongLengthTests(TestCase):
    """`format_song_length()` renders a duration the way a musician says it."""

    def test_under_ten_minutes_is_unpadded(self):
        """A duration under ten minutes renders as M:SS, with no leading zero on the minutes."""
        self.assertEqual(format_song_length(timedelta(minutes=3, seconds=45)), '3:45')

    def test_seconds_are_always_zero_padded(self):
        """Seconds under ten are zero-padded so the colon separator stays unambiguous."""
        self.assertEqual(format_song_length(timedelta(minutes=4, seconds=5)), '4:05')

    def test_ten_minutes_and_above_pads_to_two_digit_minutes(self):
        """At ten minutes and above the minutes field is naturally two digits."""
        self.assertEqual(format_song_length(timedelta(minutes=12, seconds=5)), '12:05')

    def test_over_an_hour_renders_in_minutes(self):
        """An hour-and-a-quarter renders as 75:00, not 1:15:00 (correct under the rule, irrelevant in practice)."""
        self.assertEqual(format_song_length(timedelta(hours=1, minutes=15)), '75:00')

    def test_zero_minutes_renders_a_zero(self):
        """A sub-minute duration keeps an explicit 0 in the minutes field."""
        self.assertEqual(format_song_length(timedelta(seconds=30)), '0:30')

    def test_none_renders_as_empty(self):
        """A missing duration renders as the empty string, so an unbound form shows a blank box."""
        self.assertEqual(format_song_length(None), '')

    def test_sub_second_precision_is_truncated(self):
        """Fractional seconds (as Spotify's milliseconds give) truncate rather than rendering a decimal."""
        self.assertEqual(format_song_length(timedelta(minutes=3, seconds=45, milliseconds=600)), '3:45')


class SongLengthFieldParseTests(TestCase):
    """`SongLengthField.clean()` parses M:SS, MM:SS and H:MM:SS as a musician means them."""

    def setUp(self):
        """Bind an unbound field instance for the parsing assertions."""
        self.field = SongLengthField()

    def test_m_ss_is_minutes_and_seconds(self):
        """`3:45` is three minutes forty-five seconds, not three hours forty-five minutes."""
        self.assertEqual(self.field.clean('3:45'), timedelta(minutes=3, seconds=45))

    def test_mm_ss_is_minutes_and_seconds(self):
        """`12:05` is twelve minutes five seconds."""
        self.assertEqual(self.field.clean('12:05'), timedelta(minutes=12, seconds=5))

    def test_zero_minutes_parses(self):
        """`0:30` is thirty seconds."""
        self.assertEqual(self.field.clean('0:30'), timedelta(seconds=30))

    def test_h_mm_ss_is_hours_minutes_seconds(self):
        """`1:15:00` is an hour and a quarter."""
        self.assertEqual(self.field.clean('1:15:00'), timedelta(hours=1, minutes=15))

    def test_minutes_may_exceed_an_hour(self):
        """`75:00` — the way this field renders an hour and a quarter — parses back to the same duration."""
        self.assertEqual(self.field.clean('75:00'), timedelta(hours=1, minutes=15))

    def test_surrounding_whitespace_is_ignored(self):
        """A pasted value with stray whitespace parses rather than erroring."""
        self.assertEqual(self.field.clean('  3:45  '), timedelta(minutes=3, seconds=45))

    def test_a_timedelta_passes_through(self):
        """An initial `timedelta` (as a bound instance supplies) cleans to itself."""
        self.assertEqual(self.field.clean(timedelta(minutes=3, seconds=45)), timedelta(minutes=3, seconds=45))

    def test_round_trips_through_render_then_parse(self):
        """Every duration this field renders parses back to the identical duration."""
        for duration in (
            timedelta(seconds=1),
            timedelta(seconds=30),
            timedelta(minutes=3, seconds=45),
            timedelta(minutes=4, seconds=5),
            timedelta(minutes=9, seconds=59),
            timedelta(minutes=10),
            timedelta(minutes=12, seconds=5),
            timedelta(hours=1, minutes=15),
        ):
            with self.subTest(duration=duration):
                self.assertEqual(self.field.clean(format_song_length(duration)), duration)


class SongLengthFieldRejectionTests(TestCase):
    """Unparseable and out-of-range values raise a field error rather than coercing to a value."""

    def setUp(self):
        """Bind a required field and an optional one for the rejection assertions."""
        self.field = SongLengthField()
        self.optional_field = SongLengthField(required=False)

    def test_empty_is_required_error(self):
        """An empty value on a required field is a validation error, not a zero duration."""
        with self.assertRaises(ValidationError):
            self.field.clean('')

    def test_none_is_required_error(self):
        """A missing value on a required field is a validation error, not a zero duration."""
        with self.assertRaises(ValidationError):
            self.field.clean(None)

    def test_empty_on_optional_field_is_none(self):
        """An empty value on an optional field cleans to None, so the field is reusable where length is optional."""
        self.assertIsNone(self.optional_field.clean(''))

    def test_non_numeric_is_rejected(self):
        """Free text is a validation error."""
        with self.assertRaises(ValidationError):
            self.field.clean('three forty-five')

    def test_bare_number_is_rejected(self):
        """A colon-less number is ambiguous between minutes and seconds, so it is rejected rather than guessed at."""
        with self.assertRaises(ValidationError):
            self.field.clean('225')

    def test_seconds_of_sixty_or_more_are_rejected(self):
        """`3:60` is not a duration a musician writes, so it errors rather than rolling over to 4:00."""
        with self.assertRaises(ValidationError):
            self.field.clean('3:60')

    def test_middle_minutes_of_sixty_or_more_are_rejected_in_three_part_form(self):
        """In H:MM:SS the minutes field is a clock field, so `1:75:00` errors rather than rolling over."""
        with self.assertRaises(ValidationError):
            self.field.clean('1:75:00')

    def test_four_part_value_is_rejected(self):
        """More than three colon-separated parts is not a length."""
        with self.assertRaises(ValidationError):
            self.field.clean('1:00:00:00')

    def test_negative_value_is_rejected(self):
        """A negative length is out of range."""
        with self.assertRaises(ValidationError):
            self.field.clean('-3:45')

    def test_empty_part_is_rejected(self):
        """A dangling colon is unparseable."""
        with self.assertRaises(ValidationError):
            self.field.clean('3:')

    def test_absurdly_long_value_is_rejected(self):
        """A duration at or past 24 hours is a typo, not a song, so it is out of range."""
        with self.assertRaises(ValidationError):
            self.field.clean('1440:00')

    def test_zero_duration_is_rejected(self):
        """A zero-length song is out of range: a Song that lasts no time is a typo, not a value."""
        with self.assertRaises(ValidationError):
            self.field.clean('0:00')


class SongFormLengthTests(TestCase):
    """The existing admin Song form uses the M:SS field, so today's admin surface gets this behaviour."""

    def setUp(self):
        """Build a Semester for the Songs these forms bind to."""
        self.semester = SemesterFactory()

    def test_form_uses_the_song_length_field(self):
        """SongForm's `length` is the M:SS field, not Django's default DurationField."""
        self.assertIsInstance(SongForm().fields['length'], SongLengthField)

    def test_m_ss_input_saves_minutes_and_seconds(self):
        """An admin typing `3:45` into the Song form stores three minutes forty-five seconds."""
        form = SongForm(
            {'title': 'Some Song', 'artist': 'Some Artist', 'length': '3:45', 'notes': ''},
            instance=Song(semester=self.semester, position=1),
        )
        self.assertTrue(form.is_valid(), form.errors)
        song = form.save()
        song.refresh_from_db()
        self.assertEqual(song.length, timedelta(minutes=3, seconds=45))

    def test_unparseable_input_is_a_length_field_error(self):
        """A bad length is a per-field error on `length`, leaving the rest of the submission intact."""
        form = SongForm(
            {'title': 'Some Song', 'artist': 'Some Artist', 'length': 'about four minutes', 'notes': ''},
            instance=Song(semester=self.semester, position=1),
        )
        self.assertFalse(form.is_valid())
        self.assertIn('length', form.errors)
        self.assertEqual(list(form.errors), ['length'])

    def test_existing_length_renders_back_as_m_ss(self):
        """Editing a saved Song shows its length as M:SS, so an admin sees what they typed."""
        song = SongFactory(semester=self.semester, length=timedelta(minutes=12, seconds=5))
        self.assertIn('value="12:05"', SongForm(instance=song).as_p())
