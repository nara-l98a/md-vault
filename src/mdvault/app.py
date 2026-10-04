"""Local Markdown notebook with a searchable SQLite catalogue."""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
import unicodedata
import zipfile
from datetime import datetime, timezone
from pathlib import Path


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def connect_vault(vault: str | Path) -> tuple[Path, sqlite3.Connection]:
    root = Path(vault).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    (root / "notes").mkdir(exist_ok=True)
    conn = sqlite3.connect(root / ".mdvault.sqlite3")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            body TEXT NOT NULL,
            tags TEXT NOT NULL DEFAULT '[]',
            file_path TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_notes_updated ON notes(updated_at DESC);
    """)
    try:
        conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts USING fts5(title, body, tags, tokenize='unicode61 remove_diacritics 2')")
    except sqlite3.OperationalError:
        # LIKE-based search remains available on SQLite builds without FTS5.
        pass
    return root, conn


def _fts_available(conn: sqlite3.Connection) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='notes_fts'").fetchone() is not None


def _normalize_tags(tags: list[str] | None) -> list[str]:
    result = []
    for raw in tags or []:
        for part in raw.split(","):
            tag = part.strip().casefold()
            if tag and tag not in result:
                result.append(tag)
    return result


def _slug(title: str) -> str:
    value = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value).strip("-")
    return (value or "note")[:60]


def _render_markdown(note_id: int, title: str, tags: list[str], created: str, body: str) -> str:
    safe_title = " ".join(title.replace("\r", " ").splitlines()).strip()
    return (f"# {safe_title}\n\n<!-- mdvault:id={note_id} -->\n"
            f"<!-- tags: {', '.join(tags)} -->\n<!-- created: {created} -->\n\n"
            f"{body.rstrip()}\n")


def _managed_path(root: Path, relative: str) -> Path:
    """Resolve an indexed path and reject absolute or escaping paths."""
    rel = Path(relative)
    if rel.is_absolute() or ".." in rel.parts:
        raise ValueError(f"unsafe note path in index: {relative}")
    root = root.resolve()
    path = (root / rel).resolve(strict=False)
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"note path escapes vault: {relative}") from exc
    return path


def _write_note(root: Path, row: sqlite3.Row | dict) -> None:
    path = _managed_path(root, row["file_path"])
    path.parent.mkdir(parents=True, exist_ok=True)
    data = _render_markdown(row["id"], row["title"], json.loads(row["tags"]), row["created_at"], row["body"])
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(data, encoding="utf-8")
    temp.replace(path)


def _index_row(conn: sqlite3.Connection, note_id: int, title: str, body: str, tags: list[str]) -> None:
    if not _fts_available(conn):
        return
    conn.execute("DELETE FROM notes_fts WHERE rowid=?", (note_id,))
    conn.execute("INSERT INTO notes_fts(rowid,title,body,tags) VALUES(?,?,?,?)",
                 (note_id, title, body, " ".join(tags)))


def add_note(root: Path, conn: sqlite3.Connection, title: str, body: str,
             tags: list[str] | None = None) -> sqlite3.Row:
    title = " ".join(title.strip().splitlines())
    if not title:
        raise ValueError("title cannot be empty")
    if not body.strip():
        raise ValueError("body cannot be empty")
    tag_list = _normalize_tags(tags)
    stamp = now_iso()
    created_file: Path | None = None
    try:
        with conn:
            cur = conn.execute("INSERT INTO notes(title,body,tags,file_path,created_at,updated_at) "
                               "VALUES(?,?,?,'',?,?)", (title, body.rstrip(), json.dumps(tag_list), stamp, stamp))
            note_id = int(cur.lastrowid)
            relative = f"notes/{_slug(title)}-{note_id:06d}.md"
            conn.execute("UPDATE notes SET file_path=? WHERE id=?", (relative, note_id))
            row = conn.execute("SELECT * FROM notes WHERE id=?", (note_id,)).fetchone()
            _write_note(root, row)
            created_file = root / relative
            _index_row(conn, note_id, title, body.rstrip(), tag_list)
        return conn.execute("SELECT * FROM notes WHERE id=?", (note_id,)).fetchone()
    except Exception:
        if created_file and created_file.exists():
            created_file.unlink()
        raise


def _note(conn: sqlite3.Connection, note_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM notes WHERE id=?", (note_id,)).fetchone()
    if row is None:
        raise ValueError(f"note not found: {note_id}")
    return row


def update_note(root: Path, conn: sqlite3.Connection, note_id: int,
                title: str | None = None, body: str | None = None,
                tags: list[str] | None = None) -> sqlite3.Row:
    old = _note(conn, note_id)
    new_title = " ".join((title if title is not None else old["title"]).strip().splitlines())
    new_body = body if body is not None else old["body"]
    new_tags = _normalize_tags(tags) if tags is not None else json.loads(old["tags"])
    if not new_title:
        raise ValueError("title cannot be empty")
    if not new_body.strip():
        raise ValueError("body cannot be empty")
    stamp = now_iso()
    updated = dict(old)
    updated.update(title=new_title, body=new_body.rstrip(), tags=json.dumps(new_tags), updated_at=stamp)
    _write_note(root, updated)
    try:
        with conn:
            conn.execute("UPDATE notes SET title=?,body=?,tags=?,updated_at=? WHERE id=?",
                         (updated["title"], updated["body"], updated["tags"], stamp, note_id))
            _index_row(conn, note_id, new_title, new_body.rstrip(), new_tags)
    except Exception:
        _write_note(root, old)
        raise
    return _note(conn, note_id)


def delete_note(root: Path, conn: sqlite3.Connection, note_id: int) -> None:
    row = _note(conn, note_id)
    path = _managed_path(root, row["file_path"])
    tombstone = path.with_suffix(path.suffix + ".deleting")
    if path.exists():
        path.replace(tombstone)
    try:
        with conn:
            if _fts_available(conn):
                conn.execute("DELETE FROM notes_fts WHERE rowid=?", (note_id,))
            conn.execute("DELETE FROM notes WHERE id=?", (note_id,))
    except Exception:
        if tombstone.exists():
            tombstone.replace(path)
        raise
    if tombstone.exists():
        tombstone.unlink()


def list_notes(conn: sqlite3.Connection, tag: str | None = None, limit: int = 50) -> list[sqlite3.Row]:
    if limit < 1 or limit > 1000:
        raise ValueError("limit must be between 1 and 1000")
    rows = conn.execute("SELECT * FROM notes ORDER BY updated_at DESC, id DESC").fetchall()
    if tag:
        wanted = tag.strip().casefold()
        rows = [row for row in rows if wanted in json.loads(row["tags"])]
    return list(rows[:limit])


def search_notes(conn: sqlite3.Connection, query: str, limit: int = 20) -> list[sqlite3.Row]:
    if limit < 1 or limit > 1000:
        raise ValueError("limit must be between 1 and 1000")
    terms = re.findall(r"[^\W_]+", query, flags=re.UNICODE)
    if not terms:
        raise ValueError("search query must contain letters or numbers")
    if _fts_available(conn):
        match = " AND ".join('"' + term.replace('"', '""') + '"' for term in terms)
        try:
            return list(conn.execute("SELECT n.* FROM notes n JOIN notes_fts f ON f.rowid=n.id "
                                     "WHERE notes_fts MATCH ? ORDER BY bm25(notes_fts), n.id DESC LIMIT ?",
                                     (match, limit)))
        except sqlite3.OperationalError:
            pass
    clauses, params = [], []
    for term in terms:
        clauses.append("(lower(title) LIKE ? OR lower(body) LIKE ? OR lower(tags) LIKE ?)")
        pattern = f"%{term.casefold()}%"
        params.extend((pattern, pattern, pattern))
    params.append(limit)
    return list(conn.execute("SELECT * FROM notes WHERE " + " AND ".join(clauses) +
                             " ORDER BY updated_at DESC LIMIT ?", params))


def all_tags(conn: sqlite3.Connection) -> list[tuple[str, int]]:
    counts: dict[str, int] = {}
    for row in conn.execute("SELECT tags FROM notes"):
        for tag in json.loads(row["tags"]):
            counts[tag] = counts.get(tag, 0) + 1
    return sorted(counts.items(), key=lambda item: item[0])


def export_vault(root: Path, conn: sqlite3.Connection, destination: str | Path) -> int:
    """Export managed Markdown notes and metadata to a new ZIP without altering the vault."""
    target = Path(destination).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    rows = conn.execute("SELECT * FROM notes ORDER BY id").fetchall()
    entries: list[tuple[str, Path]] = []
    manifest = []
    for row in rows:
        rel = Path(row["file_path"])
        source = _managed_path(root, row["file_path"])
        if not source.is_file():
            raise ValueError(f"note file is missing: {row['file_path']}")
        entries.append((rel.as_posix(), source))
        manifest.append({"id": row["id"], "title": row["title"], "tags": json.loads(row["tags"]),
                         "path": rel.as_posix(), "created_at": row["created_at"],
                         "updated_at": row["updated_at"]})
    if target.exists():
        raise FileExistsError(f"refusing to overwrite existing export: {target}")
    try:
        with zipfile.ZipFile(target, mode="x", compression=zipfile.ZIP_DEFLATED) as archive:
            for archive_name, source in entries:
                archive.write(source, archive_name)
            archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    except Exception:
        if target.exists():
            target.unlink()
        raise
    return len(entries)


def reindex(root: Path, conn: sqlite3.Connection) -> int:
    """Rebuild SQLite records and FTS index from managed Markdown files."""
    pattern = re.compile(r"^<!-- mdvault:id=(\d+) -->\s*$", re.M)
    tag_pattern = re.compile(r"^<!-- tags: (.*?) -->\s*$", re.M)
    created_pattern = re.compile(r"^<!-- created: (.*?) -->\s*$", re.M)
    notes_dir = root / "notes"
    parsed = []
    for path in sorted(notes_dir.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        id_match = pattern.search(text)
        title_match = re.search(r"^#\s+(.+?)\s*$", text, re.M)
        if not id_match or not title_match:
            raise ValueError(f"not a managed Markdown note: {path}")
        note_id = int(id_match.group(1))
        tag_match = tag_pattern.search(text)
        tags = _normalize_tags((tag_match.group(1).split(",") if tag_match and tag_match.group(1) else []))
        created_match = created_pattern.search(text)
        created = created_match.group(1) if created_match else now_iso()
        body = text[title_match.end():]
        body = re.sub(r"\A\s*(?:<!-- mdvault:.*?-->\s*)?(?:<!-- tags:.*?-->\s*)?(?:<!-- created:.*?-->\s*)?", "", body, count=1, flags=re.S).strip()
        if not body:
            body = "(empty note)"
        parsed.append((note_id, title_match.group(1).strip(), body, json.dumps(tags),
                       path.relative_to(root).as_posix(), created, now_iso(), tags))
    with conn:
        if _fts_available(conn):
            conn.execute("DELETE FROM notes_fts")
        conn.execute("DELETE FROM notes")
        for note_id, title, body, tags_json, relpath, created, updated, tags in parsed:
            conn.execute("INSERT INTO notes(id,title,body,tags,file_path,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
                         (note_id, title, body, tags_json, relpath, created, updated))
            _index_row(conn, note_id, title, body, tags)
    return len(parsed)


def _display(row: sqlite3.Row) -> None:
    tags = ", ".join(json.loads(row["tags"])) or "—"
    preview = " ".join(row["body"].split())
    if len(preview) > 160:
        preview = preview[:157] + "..."
    print(f"[{row['id']}] {row['title']}  (tags: {tags})\n    {preview}\n    {row['file_path']}")


def _positive_id(value: str) -> int:
    try:
        note_id = int(value)
        if note_id < 1:
            raise ValueError
        return note_id
    except ValueError as exc:
        raise argparse.ArgumentTypeError("note ID must be a positive integer") from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mdvault", description="A searchable local Markdown notebook.")
    parser.add_argument("--vault", default=os.getenv("MDVAULT_HOME", "~/Documents/md-vault"),
                        help="vault directory (default: %(default)s)")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init", help="create the vault and search index")
    add = sub.add_parser("add", help="create a Markdown note")
    add.add_argument("--title", required=True); add.add_argument("--body", required=True)
    add.add_argument("--tags", nargs="*", default=[])
    ls = sub.add_parser("list", help="list notes, optionally filtered by exact tag")
    ls.add_argument("--tag"); ls.add_argument("--limit", type=int, default=50)
    search = sub.add_parser("search", help="search note titles, bodies and tags")
    search.add_argument("query"); search.add_argument("--limit", type=int, default=20)
    show = sub.add_parser("show", help="display a complete note")
    show.add_argument("id", type=_positive_id)
    edit = sub.add_parser("update", help="update selected note fields")
    edit.add_argument("id", type=_positive_id); edit.add_argument("--title"); edit.add_argument("--body")
    edit.add_argument("--tags", nargs="*")
    delete = sub.add_parser("delete", help="delete a note and its Markdown file")
    delete.add_argument("id", type=_positive_id)
    sub.add_parser("tags", help="list tags and note counts")
    sub.add_parser("reindex", help="rebuild the catalogue from Markdown files")
    export = sub.add_parser("export", help="export managed Markdown notes and metadata to a new ZIP")
    export.add_argument("filename", help="new ZIP path (existing files are never overwritten)")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root, conn = connect_vault(args.vault)
    try:
        if args.command == "init":
            print(f"Vault ready: {root}")
        elif args.command == "add":
            row = add_note(root, conn, args.title, args.body, args.tags)
            print(f"Created note [{row['id']}]: {row['file_path']}")
        elif args.command == "list":
            rows = list_notes(conn, args.tag, args.limit)
            for row in rows:
                _display(row)
            if not rows:
                print("No notes found.")
        elif args.command == "search":
            rows = search_notes(conn, args.query, args.limit)
            for row in rows:
                _display(row)
            if not rows:
                print("No matching notes.")
        elif args.command == "show":
            row = _note(conn, args.id)
            print(f"# {row['title']}\n\nID: {row['id']}\nTags: {', '.join(json.loads(row['tags'])) or '—'}\n"
                  f"Created: {row['created_at']}\nUpdated: {row['updated_at']}\nFile: {row['file_path']}\n\n{row['body']}")
        elif args.command == "update":
            if args.title is None and args.body is None and args.tags is None:
                raise ValueError("provide at least one of --title, --body or --tags")
            row = update_note(root, conn, args.id, args.title, args.body, args.tags)
            print(f"Updated note [{row['id']}]: {row['file_path']}")
        elif args.command == "delete":
            delete_note(root, conn, args.id)
            print(f"Deleted note [{args.id}].")
        elif args.command == "tags":
            tags = all_tags(conn)
            for tag, count in tags:
                print(f"{tag}: {count}")
            if not tags:
                print("No tags yet.")
        elif args.command == "reindex":
            count = reindex(root, conn)
            print(f"Reindexed {count} Markdown note(s).")
        elif args.command == "export":
            count = export_vault(root, conn, args.filename)
            print(f"Exported {count} Markdown note(s) to {args.filename}")
        return 0
    except (ValueError, OSError, sqlite3.Error) as exc:
        print(f"mdvault: error: {exc}", file=sys.stderr)
        return 2
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
