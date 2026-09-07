#!/usr/bin/env python3
"""Find candidate local Codex source threads for a user-supplied excerpt.

Read-only adapter for local JSONL history, not a public Codex API. No tool/system
messages, persistent full-history index, or network requests. Never guess among
multiple matching threads. The caller decides whether to associate a result.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import unicodedata


def normalized_with_map(text):
    """Return normalized text and each character's range in the source text.

    These are source-message Unicode offsets, NEVER DOM/UTF-16 offsets.
    Markdown approximation may miss a rendered selection; it never fabricates a
    source range. Kept characters map back to their actual source positions.
    """
    tokens = [(char, i, i + 1) for i, ch in enumerate(text)
              for char in unicodedata.normalize("NFKC", ch)]

    def remove(pattern, keep_group=None):
        nonlocal tokens
        value = "".join(t[0] for t in tokens)
        kept, last = [], 0
        for match in re.finditer(pattern, value):
            kept.extend(tokens[last:match.start()])
            if keep_group is not None:
                kept.extend(tokens[match.start(keep_group):match.end(keep_group)])
            last = match.end()
        kept.extend(tokens[last:])
        tokens = kept

    remove(r"```[^\n]*\n")
    remove(r"!?\[([^\]]+)\]\([^\n)]*\)", 1)
    remove(r"(?m)^\s{0,3}(?:#{1,6}\s+|>\s?|[-*+]\s+)")
    remove(r"[*`_~]")
    collapsed = []
    for char, start, end in tokens:
        if char.isspace():
            if collapsed and collapsed[-1][0] == " ":
                collapsed[-1] = (" ", collapsed[-1][1], end)
            elif collapsed:
                collapsed.append((" ", start, end))
        else:
            collapsed.append((char, start, end))
    if collapsed and collapsed[-1][0] == " ":
        collapsed.pop()
    return "".join(t[0] for t in collapsed), [(t[1], t[2]) for t in collapsed]


def normalized(text):
    return normalized_with_map(text)[0]


def occurrences(text, quote):
    start = 0
    while quote:
        start = text.find(quote, start)
        if start < 0:
            return
        yield start, start + len(quote)
        start += 1


def source_ranges(text, quote):
    matches = {(start, end): "exact" for start, end in occurrences(text, quote)}
    value, mapping = normalized_with_map(text)
    needle = normalized(quote)
    for start, end in occurrences(value, needle):
        matches.setdefault((mapping[start][0], mapping[end - 1][1]), "normalized")
    return [(start, end, matches[start, end]) for start, end in sorted(matches)]


def message_text(payload):
    if not isinstance(payload, dict) or payload.get("type") != "message":
        return None
    if payload.get("role") not in ("assistant", "user"):
        return None
    if payload.get("role") == "assistant" and payload.get("channel") not in (None, "final", "commentary"):
        return None
    content = payload.get("content", [])
    if not isinstance(content, list):
        return None
    return "\n".join(part["text"] for part in content if isinstance(part, dict)
                     and part.get("type") in ("input_text", "output_text", "text")
                     and isinstance(part.get("text"), str))


def question_title(text):
    """Keep the visible request, excluding host context and tool reply wrappers."""
    value = text.strip()
    if value.startswith(("<environment_context>", "<recommended_plugins>", "<send_user_message_question_reply>")):
        return ""
    value = value.rsplit("## My request:", 1)[-1]
    return " ".join(value.split())[:160]


def resolve(quote, root, min_chars=12):
    needle = normalized(quote)
    if len(needle) < min_chars:
        return {"candidates": [], "reason": "too_short", "incomplete": False}
    titles = {}
    try:
        with (root / "session_index.jsonl").open(encoding="utf-8") as f:
            for line in f:
                try:
                    item = json.loads(line)
                    titles[item["id"]] = item.get("thread_name", "")
                except (ValueError, KeyError, TypeError):
                    continue
    except OSError:
        pass
    found = {}
    incomplete = False
    paths = sorted({p for folder in ("sessions", "archived_sessions")
                    for p in (root / folder).rglob("*.jsonl")})
    for path in paths:
        meta = None
        turn_id = ""
        message_index = 0
        try:
            with path.open(encoding="utf-8") as f:
                for line_no, line in enumerate(f, 1):
                    try:
                        item = json.loads(line)
                    except ValueError:
                        # Do not auto-associate after a partial or corrupt read.
                        incomplete = True
                        continue
                    if not isinstance(item, dict):
                        incomplete = True
                        continue
                    payload = item.get("payload", {})
                    if not isinstance(payload, dict):
                        continue
                    if item.get("type") == "session_meta":
                        meta = payload
                    if item.get("type") == "turn_context":
                        turn_id = payload.get("turn_id", "")
                    if item.get("type") != "response_item" or not meta:
                        continue
                    text = message_text(payload)
                    if text is None:
                        continue
                    message_index += 1
                    tid = meta.get("id")
                    if not isinstance(tid, str):
                        continue
                    for start, end, match in source_ranges(text, quote):
                        anchor = {"version": 1, "log_path": str(path.resolve()), "log_line": line_no,
                                  "message_index": message_index, "start_offset": start, "end_offset": end,
                                  "offset_unit": "unicode_codepoint", "coordinate_space": "source_message_text",
                                  "matched_text": text[start:end], "text_sha256": hashlib.sha256(text.encode()).hexdigest(),
                                  "prefix": text[max(0, start - 100):start], "suffix": text[end:end + 100]}
                        if isinstance(payload.get("id"), str):
                            anchor["message_id"] = payload["id"]
                        if isinstance(turn_id, str) and turn_id:
                            anchor["turn_id"] = turn_id
                        candidate = {"thread_id": tid, "thread_title": titles.get(tid, ""),
                                     "project": meta.get("cwd", ""), "match": match, "anchor": anchor}
                        # Same words in another message or another location remain distinct.
                        key = (tid, anchor.get("message_id") or message_index, start, end)
                        found.setdefault(key, candidate)
        except (OSError, UnicodeError):
            incomplete = True
    return {"candidates": list(found.values()), "incomplete": incomplete,
            "reason": "matched" if found else "not_found"}


def read_position(anchor, thread_id, root):
    """Verify and read a saved position; never silently relocate changed text."""
    if anchor.get("coordinate_space") == "rendered_message_text":
        from marks import validate
        try:
            validate({"anchor": anchor}, partial=True)
        except (ValueError, UnicodeError, TypeError, KeyError):
            return {"status": "changed"}
        return {"status": "snapshot_verified", "text": anchor["snapshot_text"],
                "start_offset": anchor["start_offset"], "end_offset": anchor["end_offset"],
                "offset_unit": "unicode_codepoint", "coordinate_space": "rendered_message_text",
                "turn_title": anchor.get("turn_title", ""),
                "message_id": anchor["message_id"], "captured_at": anchor.get("captured_at", "")}
    if not {"start_offset", "end_offset", "text_sha256"} <= anchor.keys():
        return {"status": "unrecorded"}
    roots = [(root / folder).resolve() for folder in ("sessions", "archived_sessions")]
    paths = []
    original = Path(anchor.get("log_path", "")).resolve()
    if any(folder in original.parents for folder in roots) and original.is_file():
        paths.append(original)
    # A session can move to archived_sessions; identify it by metadata, not path.
    paths += [p for folder in roots for p in folder.rglob("*.jsonl") if p not in paths]
    changed = False
    for path in paths:
        tid, index = None, 0
        current_turn, turn_title = "", ""
        try:
            with path.open(encoding="utf-8") as f:
                for line in f:
                    try:
                        item = json.loads(line)
                    except ValueError:
                        continue
                    if not isinstance(item, dict):
                        continue
                    payload = item.get("payload", {})
                    if item.get("type") == "session_meta" and isinstance(payload, dict):
                        tid = payload.get("id")
                    if item.get("type") == "turn_context" and isinstance(payload, dict):
                        incoming = payload.get("turn_id", "")
                        if incoming != current_turn:
                            current_turn, turn_title = incoming, ""
                    if tid != thread_id or item.get("type") != "response_item":
                        continue
                    text = message_text(payload)
                    if text is None:
                        continue
                    index += 1
                    if payload.get("role") == "user":
                        turn_title = question_title(text) or turn_title
                    same_message = (payload.get("id") == anchor["message_id"] if anchor.get("message_id")
                                    else index == anchor.get("message_index"))
                    if not same_message:
                        continue
                    start, end = anchor["start_offset"], anchor["end_offset"]
                    if hashlib.sha256(text.encode()).hexdigest() != anchor["text_sha256"] or not 0 <= start < end <= len(text) or text[start:end] != anchor.get("matched_text"):
                        changed = True
                        continue
                    return {"status": "verified", "text": text, "start_offset": start, "end_offset": end,
                            "offset_unit": "unicode_codepoint", "coordinate_space": "source_message_text",
                            "turn_id": current_turn, "turn_title": turn_title}
        except (OSError, UnicodeError):
            continue
    return {"status": "changed" if changed else "missing"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))))
    parser.add_argument("--read-position", action="store_true")
    args = parser.parse_args()
    try:
        data = json.load(sys.stdin)
        if args.read_position:
            from marks import validate
            anchor = validate({"anchor": data["anchor"]}, partial=True)["anchor"]
            result = read_position(anchor, data["thread_id"], args.root)
        else:
            quote = data["quote"]
            if not isinstance(quote, str) or len(quote) > 100_000:
                raise ValueError("Invalid quote")
            result = resolve(quote, args.root)
        print(json.dumps(result, ensure_ascii=False))
    except (ValueError, KeyError, OSError) as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        sys.exit(1)
