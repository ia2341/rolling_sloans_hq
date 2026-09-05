"""Resolves Vite's build manifest into the asset tags `SpaIndexView` serves (issue #325)."""

import json
from dataclasses import dataclass
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

_BUILD_COMMAND_HINT = (
    'Run `npm run build` inside frontend/ (or point VITE_DEV_SERVER_URL at a '
    'running `npm run dev`) before requesting the SPA shell.'
)

# Keyed by manifest path, holding (mtime, parsed manifest) so a rebuild is
# picked up without a server restart while production does one disk read
# per deploy rather than one per request (issue #325).
_manifest_cache: dict[Path, tuple[float, dict]] = {}


@dataclass(frozen=True)
class SpaAssets:
    """The tags `SpaIndexView` injects into the shell document for one Vite build."""

    script_url: str
    modulepreload_urls: tuple[str, ...]
    stylesheet_urls: tuple[str, ...]


def build_output_exists() -> bool:
    """Return whether the Vite build manifest is present on disk, for the deploy-time system check."""
    return settings.FRONTEND_MANIFEST_PATH.exists()


def _read_manifest() -> dict:
    """Parse the Vite manifest at `FRONTEND_MANIFEST_PATH`, cached by the file's mtime."""
    manifest_path = settings.FRONTEND_MANIFEST_PATH
    try:
        mtime = manifest_path.stat().st_mtime
    except OSError as exc:
        raise ImproperlyConfigured(
            f'No Vite build manifest found at {manifest_path}. {_BUILD_COMMAND_HINT}'
        ) from exc

    cached = _manifest_cache.get(manifest_path)
    if cached is not None and cached[0] == mtime:
        return cached[1]

    try:
        manifest = json.loads(manifest_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise ImproperlyConfigured(
            f'Could not parse the Vite build manifest at {manifest_path}. {_BUILD_COMMAND_HINT}'
        ) from exc

    _manifest_cache[manifest_path] = (mtime, manifest)
    return manifest


def get_spa_assets() -> SpaAssets:
    """Return the hashed script/stylesheet/modulepreload URLs for the SPA's entry, from the Vite manifest."""
    manifest = _read_manifest()
    entry = manifest.get(settings.FRONTEND_ENTRY)
    if entry is None:
        raise ImproperlyConfigured(
            f'The Vite build manifest at {settings.FRONTEND_MANIFEST_PATH} has no '
            f'entry for {settings.FRONTEND_ENTRY!r}. {_BUILD_COMMAND_HINT}'
        )

    static_url = settings.STATIC_URL
    stylesheet_urls = tuple(f'{static_url}{css}' for css in entry.get('css', []))

    modulepreload_urls = []
    for imported_key in entry.get('imports', []):
        imported_entry = manifest.get(imported_key)
        if imported_entry is not None:
            modulepreload_urls.append(f'{static_url}{imported_entry["file"]}')

    return SpaAssets(
        script_url=f'{static_url}{entry["file"]}',
        modulepreload_urls=tuple(modulepreload_urls),
        stylesheet_urls=stylesheet_urls,
    )
