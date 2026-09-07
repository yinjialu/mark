#!/usr/bin/env python3
"""Read only verified rendered-message positions for explicitly requested messages."""
import json
import sqlite3
import sys
from contextlib import closing

from marks import default_db, validate, UUID_RE


def list_underlines(payload):
    if not isinstance(payload, dict) or set(payload) != {'messages'}:
        raise ValueError('Invalid request')
    messages = payload['messages']
    if not isinstance(messages, list) or not 1 <= len(messages) <= 100:
        raise ValueError('Invalid message count')
    pairs = set()
    for item in messages:
        if (not isinstance(item, dict) or set(item) != {'thread_id', 'message_id'}
                or not isinstance(item['thread_id'], str) or not UUID_RE.fullmatch(item['thread_id'])
                or not isinstance(item['message_id'], str) or not 0 < len(item['message_id']) <= 200):
            raise ValueError('Invalid message identity')
        pairs.add((item['thread_id'], item['message_id']))
    path = default_db().resolve()
    if not path.exists():
        return {'ok': True, 'marks': []}
    conditions = ' OR '.join("(json_extract(data, '$.thread_id') = ? AND json_extract(data, '$.anchor.message_id') = ?)" for _ in pairs)
    args = [value for pair in sorted(pairs) for value in pair]
    result = []
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=2)) as db:
        db.execute('PRAGMA query_only = ON')
        rows = db.execute('SELECT id, data FROM marks WHERE deleted_at IS NULL AND (' + conditions + ') LIMIT 1001', args)
        for index, (mark_id, raw) in enumerate(rows):
            if index >= 1000:
                raise ValueError('Too many positions')
            try:
                data = validate(json.loads(raw))
                anchor = data.get('anchor', {})
                if anchor.get('coordinate_space') == 'rendered_block':
                    result.append({'mark_id': mark_id, 'thread_id': data['thread_id'], 'message_id': anchor['message_id'],
                                   'block_kind': anchor['block_kind'], 'block_index': anchor['block_index'],
                                   'block_source_hash': anchor['block_source_hash']})
                    continue
                if anchor.get('coordinate_space') != 'rendered_message_text':
                    continue  # Markdown source offsets are not DOM offsets.
                result.append({'mark_id': mark_id, 'thread_id': data['thread_id'],
                               'message_id': anchor['message_id'], 'text_sha256': anchor['text_sha256'],
                               'start_utf16': anchor['dom_start_offset'], 'end_utf16': anchor['dom_end_offset']})
            except (ValueError, TypeError, KeyError, UnicodeError):
                continue  # Corrupt/legacy anchors must never underline a guessed occurrence.
    return {'ok': True, 'marks': result}


if __name__ == '__main__':
    try:
        raw = sys.stdin.read(100001)
        if len(raw) > 100000:
            raise ValueError('Request too large')
        print(json.dumps(list_underlines(json.loads(raw)), ensure_ascii=False))
    except Exception:
        print(json.dumps({'ok': False, 'error': '无法读取标记位置'}, ensure_ascii=False))
        sys.exit(1)
