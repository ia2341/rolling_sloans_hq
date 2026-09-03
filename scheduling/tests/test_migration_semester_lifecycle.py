"""The 0015 data migration backfilling the semester lifecycle onto existing rows (issue #167)."""

from importlib import import_module

from django.apps import apps
from django.test import TestCase

from scheduling.factories import SemesterFactory
from scheduling.models import Semester

# The migration module's name starts with a digit, so it can't be imported by name.
_migration = import_module('scheduling.migrations.0015_semester_lifecycle')
publish_the_outgoing_current_semester = _migration.publish_the_outgoing_current_semester
unpublish_every_semester = _migration.unpublish_every_semester


class PublishTheOutgoingCurrentSemesterTests(TestCase):
    """The backfill leaves what members see unchanged: the greatest-id row stays visible, older rows become drafts."""

    def test_publishes_only_the_greatest_id_row(self):
        """Exactly the row the outgoing get_current_semester() returned gets a published_at; every other stays null."""
        oldest = SemesterFactory(draft=True)
        older = SemesterFactory(draft=True)
        newest = SemesterFactory(draft=True)

        publish_the_outgoing_current_semester(apps, None)

        for semester in (oldest, older, newest):
            semester.refresh_from_db()
        self.assertIsNotNone(newest.published_at)
        self.assertIsNone(older.published_at)
        self.assertIsNone(oldest.published_at)

    def test_a_single_existing_row_is_published(self):
        """A database holding one Semester keeps showing it to members after the migration."""
        only = SemesterFactory(draft=True)

        publish_the_outgoing_current_semester(apps, None)

        only.refresh_from_db()
        self.assertIsNotNone(only.published_at)

    def test_an_empty_database_is_left_alone(self):
        """With no Semester rows, the backfill is a no-op rather than an error."""
        publish_the_outgoing_current_semester(apps, None)

        self.assertEqual(Semester.objects.count(), 0)


class UnpublishEverySemesterTests(TestCase):
    def test_reversing_returns_every_semester_to_a_draft(self):
        """The reverse operation clears published_at everywhere, undoing the backfill."""
        published = SemesterFactory()

        unpublish_every_semester(apps, None)

        published.refresh_from_db()
        self.assertIsNone(published.published_at)
