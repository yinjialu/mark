"""Retarget only existing mark Dock tiles after a successful client switch."""
from copy import deepcopy
from pathlib import Path
from urllib.parse import unquote, urlparse
import plistlib
import subprocess
import uuid


def tile_path(tile):
    url = tile.get('tile-data', {}).get('file-data', {}).get('_CFURLString', '')
    parsed = urlparse(url)
    if parsed.scheme != 'file' or parsed.netloc not in ('', 'localhost'):
        return None
    return Path(unquote(parsed.path)).resolve()


def updated_tiles(tiles, state, target, official=None):
    builds = (state / 'builds').resolve()
    target = target.resolve()
    official = official.resolve() if official else None
    result, inserted = [], False
    for tile in tiles:
        path = tile_path(tile)
        managed = path is not None and path.is_relative_to(builds) and path.suffix == '.app'
        if not managed and not (official and path == official):
            result.append(tile)
            continue
        if inserted:
            continue
        replacement = deepcopy(tile)
        data = replacement['tile-data']
        for key in ('book', 'file-mod-date', 'parent-mod-date'):
            data.pop(key, None)
        data.update({'file-label': 'ChatGPT mark', 'bundle-identifier': 'com.openai.codex',
                     'file-data': {'_CFURLString': target.as_uri() + '/', '_CFURLStringType': 15}, 'file-type': 41})
        result.append(replacement)
        inserted = True
    # Automatic upgrades respect a user's choice to unpin mark.
    if official and not inserted:
        result.append({'tile-type': 'file-tile', 'tile-data': {
            'file-label': 'ChatGPT mark', 'bundle-identifier': 'com.openai.codex', 'file-type': 41,
            'file-data': {'_CFURLString': target.as_uri() + '/', '_CFURLStringType': 15}}})
    return result


def sync_dock(state, target, official=None):
    raw = subprocess.run(['/usr/bin/defaults', 'export', 'com.apple.dock', '-'],
                         check=True, capture_output=True).stdout
    original = plistlib.loads(raw).get('persistent-apps', [])
    updated = updated_tiles(original, state, target, official)
    if updated == original:
        return False
    backups = state / 'dock-backups'
    backups.mkdir(parents=True, exist_ok=True)
    backup = backups / (uuid.uuid4().hex + '.plist')
    backup.write_bytes(plistlib.dumps({'persistent-apps': original}))
    backup.chmod(0o600)
    # Write only this preference key; preserve other Dock settings.
    subprocess.run(['/usr/bin/defaults', 'write', 'com.apple.dock', 'persistent-apps', '-array',
                    *[plistlib.dumps(tile).decode() for tile in updated]], check=True, capture_output=True)
    subprocess.run(['/usr/bin/killall', 'Dock'], check=False, capture_output=True)
    return True
