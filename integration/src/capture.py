#!/usr/bin/env python3
"""Explicit toolbar click -> existing local marks database. No shell or network."""
import json
import hashlib
from datetime import datetime, timezone
from functools import lru_cache
import os
from pathlib import Path
import sys

from marks import Store, default_db, validate
from resolve_source import resolve, message_text, question_title


@lru_cache(maxsize=32)
def _source_index(root_value, thread_id):
    """Index one known task once; current history filenames may include a turn suffix."""
    root = Path(root_value)
    labels = {}
    try:
        with (root / 'session_index.jsonl').open(encoding='utf-8') as index:
            for line in index:
                try:
                    item = json.loads(line)
                    if item.get('id') == thread_id and isinstance(item.get('thread_name'), str):
                        labels['thread_title'] = item['thread_name'][:160]
                except (ValueError, AttributeError):
                    continue
    except (OSError, UnicodeError):
        pass
    messages = {}
    for folder in ("sessions", "archived_sessions"):
        for path in (root / folder).rglob("*" + thread_id + "*.jsonl"):
            try:
                with path.open(encoding="utf-8") as f:
                    task, turn, title, project = None, "", "", ""
                    for line in f:
                        item = json.loads(line); p = item.get("payload", {})
                        if item.get("type") == "session_meta":
                            task = p.get("id")
                            project = p.get('cwd', '')
                        if task != thread_id:
                            continue
                        if item.get("type") == "turn_context":
                            turn = p.get("turn_id", "")
                        if item.get("type") != "response_item":
                            continue
                        text = message_text(p)
                        if text is None:
                            continue
                        if p.get("role") == "user":
                            title = question_title(text) or title
                        message_id = p.get("id")
                        if isinstance(message_id, str) and message_id not in messages:
                            messages[message_id] = {"turn_id": turn, "turn_title": title,
                                                    "project": project if isinstance(project, str) else ''}
            except (OSError, ValueError, TypeError, AttributeError, UnicodeError):
                continue
    return labels, messages


def source_labels(root, thread_id, message_id):
    """Enrich only the known source task; a missing local log never loses the snapshot."""
    labels, messages = _source_index(str(Path(root).resolve()), thread_id)
    return {**labels, **messages.get(message_id, {})}


def capture(data):
    if not isinstance(data, dict) or not {"quote"} <= set(data) <= {"quote", "source"}:
        raise ValueError("Expected selected text")
    quote = validate({"quote": data["quote"]})["quote"]
    payload = {"quote": quote, "title": quote.splitlines()[0][:60]}
    root = Path(os.environ.get("CODEX_MARKS_SOURCE_ROOT", os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))))
    if "source" in data:
        s = data["source"]
        if not isinstance(s, dict) or set(s) != {"thread_id", "message_id", "text", "start_utf16", "end_utf16"}:
            raise ValueError("Invalid selection source")
        text = s["text"]
        if not isinstance(text, str) or len(text) > 1000000 or not isinstance(s["message_id"], str) or not 0 < len(s["message_id"]) <= 200:
            raise ValueError("Invalid source text or message")
        start, end = s["start_utf16"], s["end_utf16"]
        if type(start) is not int or type(end) is not int or not 0 <= start < end:
            raise ValueError("Invalid UTF-16 range")
        encoded = text.encode("utf-16-le")
        if end * 2 > len(encoded):
            raise ValueError("Range outside source")
        # Strict decoding rejects a range that splits an emoji surrogate pair.
        before = encoded[:start * 2].decode("utf-16-le")
        selected = encoded[start * 2:end * 2].decode("utf-16-le")
        if selected != quote:
            raise ValueError("Source range does not match selection")
        cp_start, cp_end = len(before), len(before) + len(selected)
        payload.update(thread_id=s["thread_id"], anchor={
            "version": 2, "message_id": s["message_id"], "snapshot_text": text,
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "start_offset": cp_start, "end_offset": cp_end,
            "offset_unit": "unicode_codepoint", "coordinate_space": "rendered_message_text",
            "dom_start_offset": start, "dom_end_offset": end,
            "matched_text": selected, "text_sha256": hashlib.sha256(text.encode()).hexdigest(),
            "prefix": text[max(0, cp_start - 100):cp_start], "suffix": text[cp_end:cp_end + 100]})
        validate(payload)  # Validate the task UUID before using it in a filename filter.
        labels = source_labels(root, s["thread_id"], s["message_id"])
        payload.update({key: labels.pop(key, '') for key in ('thread_title', 'project')})
        payload["anchor"].update(labels)
        result = Store(default_db()).add(payload)
        return {"ok": True, "created": result["created"], "mark_id": result["mark"]["id"], "position_recorded": True}
    try:
        source = resolve(quote, root)
    except (OSError, UnicodeError, ValueError):
        source = {"candidates": [], "incomplete": True}
    candidates = source["candidates"]
    if len(candidates) == 1 and not source["incomplete"]:
        payload.update({key: candidates[0][key] for key in ("thread_id", "thread_title", "project", "anchor")})
    result = Store(default_db()).add(payload)
    return {"ok": True, "created": result["created"], "mark_id": result["mark"]["id"]}


if __name__ == "__main__":
    try:
        raw = sys.stdin.read(8000001)
        if len(raw) > 8000000:
            raise ValueError("Input too large")
        print(json.dumps(capture(json.loads(raw)), ensure_ascii=False))
    except Exception:
        print(json.dumps({"ok": False, "error": "保存失败"}, ensure_ascii=False))
        sys.exit(1)
