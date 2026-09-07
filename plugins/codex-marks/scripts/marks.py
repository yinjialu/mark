#!/usr/bin/env python3
"""Local, dependency-free excerpt storage. JSON goes in and out; never eval text."""
from __future__ import annotations

import argparse
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import uuid

MAX_TEXT = 100_000
MAX_INPUT = 8_000_000
FIELDS = {"quote", "title", "note", "tags", "thread_id", "thread_title", "project", "anchor"}
TEXT_FIELDS = FIELDS - {"tags", "anchor"}
UUID_RE = re.compile(r"^[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}$")
ANCHOR_STRINGS = {"message_id", "turn_id", "prefix", "suffix", "matched_text", "text_sha256",
                  "log_path", "offset_unit", "coordinate_space", "snapshot_text", "captured_at", "turn_title",
                  "block_kind", "block_source_hash", "block_source", "asset_sha256", "asset_mime"}
ANCHOR_INTS = {"version", "message_index", "log_line", "start_offset", "end_offset",
               "dom_start_offset", "dom_end_offset", "block_index"}


def default_db() -> Path:
    if os.environ.get("CODEX_MARKS_DB"):
        return Path(os.environ["CODEX_MARKS_DB"]).expanduser()
    base = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share")))
    return base / "codex-marks/marks.sqlite3"


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def validate(data: dict, partial: bool = False) -> dict:
    if not isinstance(data, dict):
        raise ValueError("Input must be a JSON object")
    if set(data) - FIELDS:
        raise ValueError("Unknown fields: " + ", ".join(sorted(set(data) - FIELDS)))
    out = dict(data)
    for key in TEXT_FIELDS & out.keys():
        if not isinstance(out[key], str) or len(out[key]) > MAX_TEXT:
            raise ValueError(f"{key} must be a string of at most {MAX_TEXT} characters")
    if not partial and "quote" not in out:
        raise ValueError("quote is required")
    if "quote" in out and not out["quote"].strip():
        raise ValueError("quote cannot be empty")
    if out.get("thread_id") and not UUID_RE.fullmatch(out["thread_id"]):
        raise ValueError("thread_id must be a Codex UUID, or empty when unknown")
    if "tags" in out:
        tags = out["tags"]
        if not isinstance(tags, list) or len(tags) > 50:
            raise ValueError("tags must be an array with at most 50 strings")
        if any(not isinstance(t, str) or not t.strip() or len(t) > 100 for t in tags):
            raise ValueError("Each tag must be a nonempty string of at most 100 characters")
        out["tags"] = list(dict.fromkeys(t.strip() for t in tags))
    if "anchor" in out:
        anchor = out["anchor"]
        if not isinstance(anchor, dict) or set(anchor) - ANCHOR_STRINGS - ANCHOR_INTS:
            raise ValueError("Unknown anchor field")
        for key, value in anchor.items():
            limit = 1_000_000 if key == "snapshot_text" else MAX_TEXT
            if key in ANCHOR_STRINGS and (not isinstance(value, str) or len(value) > limit):
                raise ValueError(f"anchor.{key} must be a string")
            if key in ANCHOR_INTS and (type(value) is not int or value < 0):
                raise ValueError(f"anchor.{key} must be a nonnegative integer")
        if "start_offset" in anchor or "end_offset" in anchor:
            if not {"start_offset", "end_offset", "matched_text", "text_sha256", "offset_unit", "coordinate_space"} <= anchor.keys():
                raise ValueError("Position anchors require a range, matched text, hash and coordinate space")
            if anchor["end_offset"] <= anchor["start_offset"]:
                raise ValueError("Position anchor end must be greater than start")
            if anchor["end_offset"] - anchor["start_offset"] != len(anchor["matched_text"]):
                raise ValueError("Position anchor length does not match source text")
            if anchor["offset_unit"] != "unicode_codepoint" or anchor["coordinate_space"] not in ("source_message_text", "rendered_message_text"):
                raise ValueError("Unsupported position coordinate space")
            if not re.fullmatch(r"[0-9a-f]{64}", anchor["text_sha256"]):
                raise ValueError("Invalid source hash")
        if anchor.get("coordinate_space") == "rendered_message_text":
            required = {"snapshot_text", "start_offset", "end_offset", "message_id", "dom_start_offset", "dom_end_offset"}
            if not required <= anchor.keys() or not anchor["message_id"]:
                raise ValueError("Snapshot requires message identity and exact coordinates")
            text = anchor["snapshot_text"]
            start, end = anchor["start_offset"], anchor["end_offset"]
            if end > len(text) or text[start:end] != anchor["matched_text"] or hashlib.sha256(text.encode()).hexdigest() != anchor["text_sha256"]:
                raise ValueError("Snapshot content does not match its anchor")
            if (len(text[:start].encode("utf-16-le")) // 2 != anchor["dom_start_offset"]
                    or len(text[:end].encode("utf-16-le")) // 2 != anchor["dom_end_offset"]):
                raise ValueError("Snapshot UTF-16 and codepoint positions disagree")
        elif "snapshot_text" in anchor:
            raise ValueError("Snapshot text requires rendered-message coordinates")
        if anchor.get('coordinate_space') == 'rendered_block':
            kinds = {'image': 'image/png', 'mermaid': 'image/svg+xml', 'table': 'application/json'}
            if (anchor.get('block_kind') not in kinds or anchor.get('asset_mime') != kinds[anchor['block_kind']]
                    or not anchor.get('message_id') or type(anchor.get('block_index')) is not int
                    or not 0 <= anchor['block_index'] <= 10000
                    or any(not re.fullmatch(r'[0-9a-f]{64}', anchor.get(key, '')) for key in ('asset_sha256', 'block_source_hash'))
                    or 'start_offset' in anchor or 'snapshot_text' in anchor):
                raise ValueError('Invalid block anchor')
            if anchor['block_kind'] != 'image' and hashlib.sha256(anchor.get('block_source', '').encode()).hexdigest() != anchor['block_source_hash']:
                raise ValueError('Block source hash mismatch')
    return out


def identity(data: dict) -> str:
    # The same text in a different source is a separate mark. Exact bytes are preserved.
    parts = [data.get("thread_id", ""), data.get("project", ""),
             data.get("anchor", {}).get("message_id", ""), data["quote"]]
    anchor = data.get("anchor", {})
    if "start_offset" in anchor:
        # Preserve legacy fingerprints; new marks distinguish repeated occurrences.
        parts += [None if anchor.get("message_id") else anchor.get("message_index"), anchor["start_offset"], anchor["end_offset"]]
    if anchor.get("coordinate_space") == "rendered_message_text":
        parts.append("rendered_message_text")
    if anchor.get('coordinate_space') == 'rendered_block':
        parts += ['rendered_block', anchor['block_kind'], anchor['block_index'], anchor['block_source_hash']]
    return hashlib.sha256(json.dumps(parts, ensure_ascii=False).encode()).hexdigest()


class Store:
    def __init__(self, path: Path):
        self.path = path

    def connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        # Create exclusively so permissions apply from the first write.
        try:
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.close(fd)
        except FileExistsError:
            pass
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute("""CREATE TABLE IF NOT EXISTS marks (
            id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL,
            data TEXT NOT NULL, created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL, deleted_at TEXT
        )""")
        db.execute("CREATE UNIQUE INDEX IF NOT EXISTS active_fingerprint ON marks(fingerprint) WHERE deleted_at IS NULL")
        db.commit()
        return db

    @staticmethod
    def decode(row):
        result = json.loads(row["data"])
        result.update({k: row[k] for k in ("id", "created_at", "updated_at", "deleted_at")})
        tid = result.get("thread_id")
        result["source_url"] = "codex://threads/" + tid if tid else None
        result["navigation"] = "thread" if tid else "unavailable"
        anchor = result.get("anchor", {})
        result["position_status"] = "recorded" if "start_offset" in anchor else "unrecorded"
        result["mark_url"] = "codex-marks://mark/" + result["id"]
        return result

    def add(self, raw):
        data = validate(raw)
        data = {"title": "", "note": "", "tags": [], "thread_id": "", "thread_title": "",
                "project": "", "anchor": {}, **data}
        fingerprint = identity(data)
        with closing(self.connect()) as db, db:
            stamp = now()
            mark_id = str(uuid.uuid4())
            cursor = db.execute(
                "INSERT OR IGNORE INTO marks VALUES (?, ?, ?, ?, ?, NULL)",
                (mark_id, fingerprint, json.dumps(data, ensure_ascii=False), stamp, stamp))
            row = db.execute("SELECT * FROM marks WHERE fingerprint=? AND deleted_at IS NULL", (fingerprint,)).fetchone()
            return {"created": cursor.rowcount == 1, "mark": self.decode(row)}

    def get(self, mark_id):
        with closing(self.connect()) as db:
            row = db.execute("SELECT * FROM marks WHERE id=?", (mark_id,)).fetchone()
            if row is None:
                raise ValueError("Mark not found: " + mark_id)
            return self.decode(row)

    def search(self, query="", tag=None, thread_id=None, project=None, deleted=False, limit=50, offset=0):
        terms = query.casefold().split()
        with closing(self.connect()) as db:
            rows = db.execute("SELECT * FROM marks WHERE deleted_at IS " +
                              ("NOT NULL" if deleted else "NULL") + " ORDER BY created_at DESC, id DESC")
            matches = []
            for row in rows:
                mark = self.decode(row)
                if tag and tag.casefold() not in [t.casefold() for t in mark["tags"]]:
                    continue
                if thread_id and mark["thread_id"] != thread_id:
                    continue
                if project and project.casefold() not in mark["project"].casefold():
                    continue
                haystack = "\n".join([mark.get(k, "") for k in
                    ("quote", "title", "note", "thread_title", "project")] + mark["tags"]).casefold()
                if all(term in haystack for term in terms):
                    matches.append(mark)
            return {"total": len(matches), "marks": matches[offset:offset + limit], "offset": offset}

    def update(self, mark_id, raw):
        patch = validate(raw, partial=True)
        with closing(self.connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM marks WHERE id=? AND deleted_at IS NULL", (mark_id,)).fetchone()
            if not row:
                raise ValueError("Active mark not found: " + mark_id)
            previous = json.loads(row["data"])
            data = {**previous, **patch}
            if "anchor" not in patch and any(key in patch and patch[key] != previous.get(key) for key in ("quote", "thread_id")):
                data["anchor"] = {}
            db.execute("UPDATE marks SET data=?, fingerprint=?, updated_at=? WHERE id=?",
                       (json.dumps(data, ensure_ascii=False), identity(data), now(), mark_id))
        return self.get(mark_id)

    def set_deleted(self, mark_id, deleted):
        with closing(self.connect()) as db, db:
            stamp = now()
            cursor = db.execute("UPDATE marks SET deleted_at=?, updated_at=? WHERE id=?",
                                (stamp if deleted else None, stamp, mark_id))
            if cursor.rowcount == 0:
                raise ValueError("Mark not found: " + mark_id)
        return self.get(mark_id)


def md_text(text):
    # Render stored content as text, not HTML, images or active Markdown links.
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return re.sub(r"([\\`*_{}\[\]()#+.!|~-])", r"\\\1", text)


def markdown(marks):
    out = ["# Codex Marks", "", f"共 {len(marks)} 条收藏。定位链接在本机 mark 原文窗口中打开并高亮。", ""]
    for mark in marks:
        title = mark["title"] or mark["quote"].splitlines()[0][:60]
        out += ["## " + md_text(title).replace("\n", " "), ""]
        out += ["> " + md_text(line) for line in mark["quote"].split("\n")]
        out += [""]
        if mark["note"]:
            out += ["备注：" + md_text(mark["note"]), ""]
        if mark["tags"]:
            out += ["标签：" + " · ".join(md_text(t) for t in mark["tags"]), ""]
        label = md_text(mark["thread_title"] or "来源对话")
        out += [(f"来源：[{label}]({mark['source_url']})" if mark["source_url"] else "来源：未关联对话"), ""]
        out += [f"[定位原文]({mark['mark_url']})", ""]
        if mark["project"]:
            out += ["项目：" + md_text(mark["project"]), ""]
        out += ["保存时间：" + mark["created_at"], "", "收藏 ID：" + mark["id"], ""]
    return "\n".join(out)


def read_input(path):
    content = sys.stdin.read(MAX_INPUT + 1) if path == "-" else Path(path).read_text(encoding="utf-8")
    if len(content) > MAX_INPUT:
        raise ValueError("Input too large")
    return json.loads(content)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=default_db())
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("add").add_argument("--input", default="-", help="JSON file, or - for stdin")
    for name in ("get", "context", "delete", "restore", "update"):
        p = sub.add_parser(name)
        p.add_argument("id")
        if name == "update":
            p.add_argument("--input", default="-")
    for name in ("search", "export"):
        p = sub.add_parser(name)
        p.add_argument("query", nargs="?", default="")
        p.add_argument("--tag")
        p.add_argument("--thread-id")
        p.add_argument("--project")
        p.add_argument("--deleted", action="store_true")
        p.add_argument("--limit", type=int, default=50 if name == "search" else 1_000_000)
        p.add_argument("--offset", type=int, default=0)
        if name == "export":
            p.add_argument("--format", choices=["json", "markdown"], default="markdown")
    args = parser.parse_args()
    try:
        store = Store(args.db.expanduser())
        if args.command == "add":
            result = store.add(read_input(args.input))
        elif args.command == "get":
            result = store.get(args.id)
        elif args.command == "context":
            from resolve_source import read_position
            mark = store.get(args.id)
            anchor = mark["anchor"]
            root = Path(os.environ.get("CODEX_MARKS_SOURCE_ROOT", os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))))
            if anchor.get('coordinate_space') == 'rendered_block':
                from block_assets import block_context
                context = block_context(mark, args.db.expanduser())
            else:
                context = read_position(anchor, mark["thread_id"], root)
            if context["status"] not in ("verified", "snapshot_verified", "block_verified"):
                prefix, suffix = anchor.get("prefix", ""), anchor.get("suffix", "")
                selected = anchor.get("matched_text", mark["quote"])
                context.update(text=prefix + selected + suffix, start_offset=len(prefix),
                               end_offset=len(prefix) + len(selected), offset_unit="unicode_codepoint",
                               coordinate_space="saved_excerpt_context")
            result = {"mark": mark, "context": context}
        elif args.command == "update":
            result = store.update(args.id, read_input(args.input))
        elif args.command in ("delete", "restore"):
            result = store.set_deleted(args.id, args.command == "delete")
        else:
            if args.limit < 1 or args.offset < 0:
                raise ValueError("limit must be positive and offset cannot be negative")
            result = store.search(args.query, args.tag, args.thread_id, args.project,
                                  args.deleted, args.limit, args.offset)
            if args.command == "export" and args.format == "markdown":
                print(markdown(result["marks"]))
                return
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (ValueError, OSError, sqlite3.Error) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
