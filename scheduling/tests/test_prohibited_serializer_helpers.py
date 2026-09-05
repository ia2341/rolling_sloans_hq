"""Neither serializer module may import an emit-everything helper (issue #326, ADR 0005).

`dataclasses.asdict()`, `django.forms.model_to_dict()` and iterating a
model's `_meta.fields` are each a rule that says "emit every field" — the
opposite of the hand-written, name-every-field serializers this ticket
requires. This is the mechanical enforcement for the cultural rule.
"""

import ast
from pathlib import Path

from django.test import SimpleTestCase

SERIALIZER_MODULE_PATHS = (
    Path(__file__).resolve().parent.parent / 'serializers.py',
    Path(__file__).resolve().parent.parent.parent / 'identity' / 'serializers.py',
)

# Names whose presence anywhere in a serializer module (an import, or a
# reference to an already-imported module attribute) signals an
# emit-everything shortcut.
PROHIBITED_IMPORTED_NAMES = {'asdict', 'model_to_dict'}
PROHIBITED_IMPORTED_MODULES = {'dataclasses', 'django.forms', 'django.forms.models'}


def _imported_names_and_modules(source: str) -> tuple[set[str], set[str]]:
    """Return the set of imported names and the set of imported module paths in `source`."""
    tree = ast.parse(source)
    names = set()
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
            for alias in node.names:
                names.add(alias.name)
    return names, modules


class ProhibitedSerializerHelpersTests(SimpleTestCase):
    """Neither `scheduling/serializers.py` nor `identity/serializers.py` imports an emit-everything helper."""

    def test_no_serializer_module_imports_an_emit_everything_helper(self):
        """Parse each serializer module's imports and assert none names a prohibited helper or module."""
        for path in SERIALIZER_MODULE_PATHS:
            source = path.read_text()
            names, modules = _imported_names_and_modules(source)
            offending_names = names & PROHIBITED_IMPORTED_NAMES
            offending_modules = modules & PROHIBITED_IMPORTED_MODULES
            self.assertFalse(
                offending_names or offending_modules,
                f'{path} imports a prohibited emit-everything helper: '
                f'{offending_names or offending_modules}',
            )
