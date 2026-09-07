#!/usr/bin/env python3
import hashlib
import json
import os
from pathlib import Path
import sys

from marks import Store, default_db, validate
from block_assets import store_asset, MIMES
from capture import source_labels


def capture_block(payload):
    if not isinstance(payload, dict) or set(payload) != {'source', 'content'}:
        raise ValueError('Invalid block request')
    source = payload['source']
    if not isinstance(source, dict) or set(source) != {'kind', 'thread_id', 'message_id', 'block_index', 'source_hash', 'source_text', 'caption'}:
        raise ValueError('Invalid block source')
    if source['kind'] not in MIMES or not isinstance(source['message_id'], str) or not 0 < len(source['message_id']) <= 200:
        raise ValueError('Invalid block identity')
    title = {'image': '图片', 'mermaid': 'Mermaid 图表', 'table': '表格'}[source['kind']]
    quote = source['source_text'] if source['kind'] != 'image' else '[图片] ' + source['caption']
    data = {'quote': quote or '[' + title + ']', 'title': (source['caption'] or title)[:100], 'thread_id': source['thread_id'],
            'anchor': {'version': 3, 'coordinate_space': 'rendered_block', 'message_id': source['message_id'],
                       'block_kind': source['kind'], 'block_index': source['block_index'],
                       'block_source_hash': source['source_hash'], 'block_source': source['source_text'],
                       'asset_sha256': '0' * 64, 'asset_mime': MIMES[source['kind']]}}
    validate(data)
    root = Path(os.environ.get('CODEX_MARKS_SOURCE_ROOT', os.environ.get('CODEX_HOME', str(Path.home() / '.codex'))))
    labels = source_labels(root, source['thread_id'], source['message_id'])
    data.update({key: labels.pop(key, '') for key in ('thread_title', 'project')})
    data['anchor'].update(labels)
    digest, mime = store_asset(default_db(), source['kind'], payload['content'])
    data['anchor'].update(asset_sha256=digest, asset_mime=mime)
    result = Store(default_db()).add(data)
    return {'ok': True, 'mark_id': result['mark']['id'], 'created': result['created']}


if __name__ == '__main__':
    try:
        raw = sys.stdin.read(35_000_001)
        if len(raw) > 35_000_000:
            raise ValueError('Request too large')
        print(json.dumps(capture_block(json.loads(raw)), ensure_ascii=False))
    except Exception:
        print(json.dumps({'ok': False, 'error': '无法保存图片或表格'}, ensure_ascii=False))
        sys.exit(1)
