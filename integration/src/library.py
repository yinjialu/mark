#!/usr/bin/env python3
"""Bounded library operations for the trusted desktop renderer; fixed local store."""
import json
import sys
from marks import Store, default_db, UUID_RE
from block_assets import block_context
from resolve_source import read_position


def validate_request(p):
    if not isinstance(p, dict):
        raise ValueError('Invalid request')
    op = p.get('op')
    if op == 'search':
        if set(p) != {'op', 'query', 'thread_id', 'deleted', 'offset', 'limit'}:
            raise ValueError('Invalid search')
        if not isinstance(p['query'], str) or len(p['query']) > 500:
            raise ValueError('Invalid query')
        if not isinstance(p['thread_id'], str) or (p['thread_id'] and not UUID_RE.fullmatch(p['thread_id'])):
            raise ValueError('Invalid task')
        if type(p['deleted']) is not bool or type(p['offset']) is not int or not 0 <= p['offset'] <= 1000000:
            raise ValueError('Invalid page')
        if type(p['limit']) is not int or not 1 <= p['limit'] <= 100:
            raise ValueError('Invalid limit')
    elif op in ('get', 'update', 'delete', 'restore'):
        if set(p) != ({'op', 'id', 'title', 'note', 'tags'} if op == 'update' else {'op', 'id'}):
            raise ValueError('Invalid operation fields')
        if not isinstance(p['id'], str) or not UUID_RE.fullmatch(p['id']):
            raise ValueError('Invalid mark')
        if op == 'update':
            if not isinstance(p['title'], str) or len(p['title']) > 200 or not isinstance(p['note'], str) or len(p['note']) > 10000:
                raise ValueError('Invalid edit')
            if not isinstance(p['tags'], list) or len(p['tags']) > 30 or any(not isinstance(t, str) or len(t) > 50 for t in p['tags']):
                raise ValueError('Invalid tags')
    else:
        raise ValueError('Unknown operation')
    return p


def summary(m):
    a = m.get('anchor', {})
    keys = ('message_id', 'turn_id', 'turn_title', 'coordinate_space', 'text_sha256',
            'dom_start_offset', 'dom_end_offset', 'block_kind', 'block_index', 'block_source_hash')
    return {**{k: m.get(k) for k in ('id', 'title', 'note', 'tags', 'thread_id', 'thread_title', 'created_at', 'deleted_at')},
            'quote': m['quote'][:1000], 'anchor': {k: a[k] for k in keys if k in a}}


def handle(payload):
    p = validate_request(payload)
    path = default_db()
    if p['op'] == 'search' and not path.exists():
        return {'ok': True, 'marks': [], 'total': 0, 'offset': p['offset']}
    store = Store(path)
    if p['op'] == 'search':
        result = store.search(p['query'], thread_id=p['thread_id'] or None, deleted=p['deleted'], limit=p['limit'], offset=p['offset'])
        return {'ok': True, **result, 'marks': [summary(m) for m in result['marks']]}
    if p['op'] == 'update':
        return {'ok': True, 'mark': summary(store.update(p['id'], {k: p[k] for k in ('title', 'note', 'tags')}))}
    if p['op'] in ('delete', 'restore'):
        return {'ok': True, 'mark': summary(store.set_deleted(p['id'], p['op'] == 'delete'))}
    m = store.get(p['id'])
    a = m.get('anchor', {})
    if a.get('coordinate_space') == 'rendered_block':
        context = block_context(m, path)
    elif a.get('coordinate_space') == 'rendered_message_text':
        context = read_position(a, m['thread_id'], path.parent)
    else:
        # Legacy records still show their saved excerpt; no speculative relocation.
        context = {'status': 'excerpt_only', 'text': m['quote']}
    return {'ok': True, 'mark': {**summary(m), 'quote': m['quote']}, 'context': context}


if __name__ == '__main__':
    try:
        raw = sys.stdin.read(100001)
        if len(raw) > 100000:
            raise ValueError('Request too large')
        print(json.dumps(handle(json.loads(raw)), ensure_ascii=False))
    except Exception:
        print(json.dumps({'ok': False, 'error': '无法读取或更新收藏，请重试'}, ensure_ascii=False))
