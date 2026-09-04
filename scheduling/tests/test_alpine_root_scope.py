"""Static guard against issue #290: an Alpine component method reaching the component's own DOM through
`$el` instead of `$root`.

Inside an `Alpine.data()` method, `$el` is the element whose expression is being evaluated -- the button
that was clicked, the select that changed -- never reliably the element carrying `x-data`. `$root` is the
one magic property that always names the component root. issue #290's audit found every real use of
`this.$el` in this codebase (across `setlist_edit.js`, `rehearsal_generation.js`, `schedule_edit.js`,
`song_requirements_edit.js`, `rehearsal_pattern_step.js` and `assignment_picker.js`) was a component-root
lookup -- the formset's management form, the rows container, the row groups -- and every one of them broke
for some call site, immediately (a button-bound "+ Add") or eventually (an internal helper reached from
more than one place). Even the two call sites the audit found were *currently* safe only because Alpine
happened to invoke them with `$el === $root` (an `init()` bound via `x-init` on the root, and a helper
reached solely from an automatic `init()` call) were switched to `$root` too, specifically so this
invariant could hold with zero exceptions to remember or special-case here.

This is deliberately a blanket ban on `this.$el` in these files, not a parser that tries to distinguish "a
component-root lookup via $el" from some other hypothetical use -- see this module's docstring-length
comment above for why a narrow, well-commented rule beats a clever one. Nothing in this codebase's actual
JS needs the literal clicked/changed element for anything `event.target`/`event.currentTarget` (already
used throughout for exactly that) can't already provide, so the rule stays simple: reach for the
component's own DOM via `$root`; reach for the triggering element via the event, not `$el`. A future
legitimate use of `$el` for the *literal* invoking element (not a `$root`-shaped lookup) would trip this
guard -- that's an acceptable false positive for a test intentionally kept this narrow (see issue #290's
own note that a meaningful, non-brittle rule may need to be this blunt); it should read this comment, use
`event.target`/`event.currentTarget` instead, or -- if truly novel -- update this test's rationale
alongside the new code, not silently work around it.
"""

from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

# The forbidden token: any `this.$el` reference. Written with an escaped '.' so it can't accidentally
# match unrelated text, though '$el' isn't used as a substring of any other identifier in these files.
FORBIDDEN_PATTERN = 'this.$el'

JS_DIR = Path(settings.BASE_DIR) / 'scheduling' / 'static' / 'scheduling' / 'js'


def _js_files():
    """Yield every .js file under scheduling's static JS directory, sorted for stable test output."""
    return sorted(JS_DIR.glob('*.js'))


class NoAlpineComponentUsesElForComponentRootTests(SimpleTestCase):
    def test_no_js_file_reaches_the_component_root_through_el(self):
        """No file under scheduling/static/scheduling/js/ contains `this.$el` (issue #290).

        `$el` is the element whose expression Alpine is currently evaluating -- the clicked button, the
        changed select -- never reliably the `x-data` root. Every Alpine component method that wants the
        component's own DOM (a formset's management form, a rows container, a row group) must resolve it
        through `this.$root` instead. Failing here means a new or edited method reintroduced the exact bug
        issue #290 fixed: it will render, and then throw the moment anything but a root-bound `init()`
        calls it.
        """
        offenders = []
        for path in _js_files():
            text = path.read_text()
            for line_number, line in enumerate(text.splitlines(), start=1):
                if FORBIDDEN_PATTERN in line:
                    offenders.append(
                        f'{path.name}:{line_number}: uses `this.$el` to reach for component state -- '
                        f'use `this.$root` instead (issue #290): {line.strip()!r}'
                    )

        self.assertEqual(offenders, [], '\n'.join(offenders))

    def test_every_component_file_is_actually_scanned(self):
        """Guards the guard: fails loudly if the JS directory moves or empties out from under this test.

        A silently-empty file list would make the test above vacuously pass -- this pins down that the
        sweep is actually looking at the real, non-trivial set of component files.
        """
        names = {path.name for path in _js_files()}
        # Every file the issue #290 audit named explicitly, so a rename or relocation of any of them
        # fails this test rather than quietly narrowing what the sweep covers.
        expected = {
            'setlist_edit.js',
            'rehearsal_generation.js',
            'schedule_edit.js',
            'song_requirements_edit.js',
            'rehearsal_pattern_step.js',
            'assignment_picker.js',
            'roster_edit.js',
            'roster_import_step.js',
        }
        self.assertTrue(expected.issubset(names), f'expected {expected} to be a subset of {names}')
