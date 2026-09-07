"""Passive block snapshots. All asset paths are derived from checked content hashes."""
import base64
import hashlib
import html
import json
import os
from pathlib import Path
import re
import struct
import tempfile
import xml.etree.ElementTree as ET

MAX_ASSET = 24 * 1024 * 1024
MIMES = {'image': 'image/png', 'mermaid': 'image/svg+xml', 'table': 'application/json'}
EXTENSIONS = {'image/png': '.png', 'image/svg+xml': '.svg', 'application/json': '.json'}


def asset_path(db, digest, mime):
    if not re.fullmatch(r'[0-9a-f]{64}', digest) or mime not in EXTENSIONS:
        raise ValueError('Invalid asset identity')
    return Path(db).resolve().parent / 'assets' / (digest + EXTENSIONS[mime])


def table_data(raw):
    data = json.loads(raw)
    if not isinstance(data, dict) or set(data) != {'rows'} or not isinstance(data['rows'], list) or not 1 <= len(data['rows']) <= 2000:
        raise ValueError('Invalid table')
    count = 0
    for row in data['rows']:
        if not isinstance(row, list) or not 1 <= len(row) <= 200:
            raise ValueError('Invalid table row')
        for cell in row:
            count += 1
            if (not isinstance(cell, dict) or set(cell) != {'text', 'header', 'rowspan', 'colspan'}
                    or not isinstance(cell['text'], str) or len(cell['text']) > 100000
                    or type(cell['header']) is not bool
                    or any(type(cell[key]) is not int or not 1 <= cell[key] <= 2000 for key in ('rowspan', 'colspan'))):
                raise ValueError('Invalid table cell')
    if count > 20000:
        raise ValueError('Table too large')
    return data


def clean_svg(raw):
    if len(raw) > 4_000_000 or b'<!' in raw:
        raise ValueError('Unsupported SVG declarations')
    root = ET.fromstring(raw)
    if root.tag.split('}')[-1] != 'svg':
        raise ValueError('Expected SVG')
    allowed = set('svg g defs style path rect circle ellipse line polyline polygon text tspan textPath marker clipPath mask linearGradient radialGradient stop title desc pattern symbol use'.split())
    def clean(node):
        for child in list(node):
            if child.tag.split('}')[-1] not in allowed:
                node.remove(child)
            else:
                clean(child)
        for key, value in list(node.attrib.items()):
            name = key.split('}')[-1].lower()
            if name.startswith('on') or name in ('src', 'base') or (name == 'href' and not value.startswith('#')):
                del node.attrib[key]
    clean(root)
    ET.register_namespace('', 'http://www.w3.org/2000/svg')
    return ET.tostring(root, encoding='utf-8')


def store_asset(db, kind, content):
    if kind not in MIMES or not isinstance(content, str) or len(content) > 34_000_000:
        raise ValueError('Invalid block content')
    if kind == 'image':
        prefix = 'data:image/png;base64,'
        if not content.startswith(prefix):
            raise ValueError('Only decoded PNG snapshots are stored')
        raw = base64.b64decode(content[len(prefix):], validate=True)
        if len(raw) < 33 or raw[:8] != b'\x89PNG\r\n\x1a\n' or raw[12:16] != b'IHDR':
            raise ValueError('Invalid PNG')
        width, height = struct.unpack('>II', raw[16:24])
        if not 0 < width <= 20000 or not 0 < height <= 20000 or width * height > 40000000:
            raise ValueError('Image dimensions too large')
    elif kind == 'mermaid':
        raw = clean_svg(content.encode())
    else:
        raw = json.dumps(table_data(content), ensure_ascii=False, separators=(',', ':')).encode()
    if len(raw) > MAX_ASSET:
        raise ValueError('Snapshot too large')
    digest = hashlib.sha256(raw).hexdigest()
    path = asset_path(db, digest, MIMES[kind])
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.exists():
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError('Existing asset was changed')
    else:
        fd, temp = tempfile.mkstemp(prefix='.mark-', dir=path.parent)
        try:
            with os.fdopen(fd, 'wb') as out:
                out.write(raw)
            os.replace(temp, path)
        finally:
            if os.path.exists(temp):
                os.unlink(temp)
    return digest, MIMES[kind]


def block_context(mark, db):
    from marks import validate
    validate({'quote': mark['quote'], 'thread_id': mark['thread_id'], 'anchor': mark['anchor']})
    anchor = mark['anchor']
    path = asset_path(db, anchor['asset_sha256'], anchor['asset_mime'])
    raw = path.read_bytes()
    if len(raw) > MAX_ASSET or hashlib.sha256(raw).hexdigest() != anchor['asset_sha256']:
        raise ValueError('Saved snapshot changed')
    if anchor['block_kind'] == 'table':
        rows = table_data(raw)['rows']
        content = '<table>' + ''.join('<tr>' + ''.join(
            '<{tag} rowspan="{rowspan}" colspan="{colspan}">{text}</{tag}>'.format(
                tag='th' if cell['header'] else 'td', rowspan=cell['rowspan'], colspan=cell['colspan'], text=html.escape(cell['text']))
            for cell in row) + '</tr>' for row in rows) + '</table>'
    else:
        content = '<img alt="已收藏的图片或图表" src="data:' + anchor['asset_mime'] + ';base64,' + base64.b64encode(raw).decode() + '">'
    document = '''<!doctype html><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data:; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'"><style>body{margin:24px;font:15px/1.6 system-ui;color:#222;background:#fff}img{display:block;max-width:100%;height:auto}table{border-collapse:collapse}td,th{border:1px solid #ccc;padding:10px 14px;text-align:start;white-space:pre-wrap}th{background:#f3f3f3}a{pointer-events:none}</style>''' + content
    return {'status': 'block_verified', 'kind': anchor['block_kind'], 'html': document,
            'source_text': anchor.get('block_source', ''), 'turn_title': anchor.get('turn_title', '')}
