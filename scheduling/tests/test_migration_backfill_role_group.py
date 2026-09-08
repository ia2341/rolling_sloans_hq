"""The 0025 data migration's `_group_name_for()`, classifying an existing Role's name into its RoleGroup (issue #457).

Ported from `frontend/src/lib/roleColumns.ts`'s retired `classifyRole()` so
existing/seeded Roles land in the same group current display behavior
already implies. `Role.group` is non-nullable by the time this app's
migrations finish (0026), so exercising the actual `backfill_role_group()`
DB round trip would require reconstructing 0024's pre-0026 historical
schema state; this test covers the classification function it calls
instead, which is what determines correctness.
"""

from importlib import import_module

from django.test import SimpleTestCase

_group_name_for = import_module(
    'scheduling.migrations.0025_backfill_role_group',
)._group_name_for


class GroupNameForTests(SimpleTestCase):
    def test_vocal_roles_classify_as_vocals(self):
        """Any Role name containing "vocal" (case-insensitive) classifies as Vocals."""
        for name in ('Male Lead Vocalist', 'Female Backing Vocalist', 'VOCALS'):
            with self.subTest(name=name):
                self.assertEqual(_group_name_for(name), 'Vocals')

    def test_guitar_roles_classify_as_guitars(self):
        """Any Role name containing "guitar" classifies as Guitars, lead/acoustic/rhythm included."""
        for name in ('Lead Guitar', 'Rhythm Guitar', 'Acoustic Guitar'):
            with self.subTest(name=name):
                self.assertEqual(_group_name_for(name), 'Guitars')

    def test_bass_classifies_as_bass(self):
        """A Role name containing "bass" classifies as Bass."""
        self.assertEqual(_group_name_for('Bass'), 'Bass')

    def test_drums_classifies_as_drums(self):
        """A Role name containing "drum" classifies as Drums."""
        self.assertEqual(_group_name_for('Drums'), 'Drums')

    def test_key_roles_classify_as_keyboards(self):
        """A Role name containing "key" classifies as Keyboards."""
        for name in ('Keyboard', 'Keys'):
            with self.subTest(name=name):
                self.assertEqual(_group_name_for(name), 'Keyboards')

    def test_saxophone_classifies_as_saxophone(self):
        """A Role name containing "sax" classifies as Saxophone."""
        self.assertEqual(_group_name_for('Saxophone'), 'Saxophone')

    def test_trumpet_classifies_as_trumpet(self):
        """A Role name containing "trumpet" classifies as Trumpet."""
        self.assertEqual(_group_name_for('Trumpet'), 'Trumpet')

    def test_violin_classifies_as_violin(self):
        """A Role name containing "violin" classifies as Violin."""
        self.assertEqual(_group_name_for('Violin'), 'Violin')

    def test_unmatched_role_falls_back_to_catch_all(self):
        """A Role name matching none of the fixed families falls back to the Other catch-all group."""
        self.assertEqual(_group_name_for('Tambourine'), 'Other')
