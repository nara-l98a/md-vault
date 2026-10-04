import contextlib
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from mdvault.app import (add_note, all_tags, connect_vault, delete_note, export_vault,
                         list_notes, main, reindex, search_notes, update_note)


class VaultTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root, self.conn = connect_vault(Path(self.tmp.name) / "vault")

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def test_add_search_tags_markdown_and_update(self):
        row = add_note(self.root, self.conn, "Neural Networks", "A practical guide to neural network training.",
                       ["AI", "research"])
        self.assertTrue((self.root / row["file_path"]).exists())
        self.assertEqual(json.loads(row["tags"]), ["ai", "research"])
        matches = search_notes(self.conn, "neural training")
        self.assertEqual([r["id"] for r in matches], [row["id"]])
        updated = update_note(self.root, self.conn, row["id"], title="Deep Learning Notes",
                              body="A practical study of representation learning.", tags=["ML"])
        self.assertEqual(updated["title"], "Deep Learning Notes")
        self.assertEqual(json.loads(updated["tags"]), ["ml"])
        self.assertIn("# Deep Learning Notes", (self.root / updated["file_path"]).read_text())
        self.assertEqual(search_notes(self.conn, "neural"), [])
        with self.assertRaises(ValueError):
            search_notes(self.conn, "neural", limit=0)

    def test_exact_tag_filter_and_tag_counts(self):
        add_note(self.root, self.conn, "One", "First body.", ["work"])
        add_note(self.root, self.conn, "Two", "Second body.", ["work", "ideas"])
        add_note(self.root, self.conn, "Three", "Third body.", ["workshop"])
        self.assertEqual(len(list_notes(self.conn, tag="WORK")), 2)
        self.assertEqual(dict(all_tags(self.conn)), {"ideas": 1, "work": 2, "workshop": 1})

    def test_delete_and_reindex_from_markdown(self):
        row = add_note(self.root, self.conn, "Climate", "Climate adaptation and water planning.", ["field"])
        path = self.root / row["file_path"]
        text = path.read_text().replace("Climate adaptation and water planning.", "Updated climate resilience notes.")
        path.write_text(text)
        self.assertEqual(reindex(self.root, self.conn), 1)
        self.assertEqual(search_notes(self.conn, "resilience")[0]["title"], "Climate")
        delete_note(self.root, self.conn, row["id"])
        self.assertFalse(path.exists())
        self.assertEqual(list_notes(self.conn), [])

    def test_reindex_rejects_unmanaged_markdown_without_changing_index(self):
        row = add_note(self.root, self.conn, "Keep", "Existing record.")
        before = len(list_notes(self.conn))
        (self.root / "notes" / "broken.md").write_text("not a managed note")
        with self.assertRaisesRegex(ValueError, "not a managed"):
            reindex(self.root, self.conn)
        self.assertEqual(len(list_notes(self.conn)), before)
        self.assertEqual(self.conn.execute("SELECT title FROM notes WHERE id=?", (row["id"],)).fetchone()[0], "Keep")

    def test_cli_commands(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(main(["--vault", str(self.root), "add", "--title", "CLI Note",
                                   "--body", "Searchable example", "--tags", "demo"]), 0)
        self.assertIn("Created note [", output.getvalue())
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(main(["--vault", str(self.root), "search", "example"]), 0)
        self.assertIn("CLI Note", output.getvalue())

    def test_export_archive_and_refuse_overwrite(self):
        row = add_note(self.root, self.conn, "Release Plan", "Ship the tested package.", ["work"])
        archive_path = Path(self.tmp.name) / "vault-export.zip"
        self.assertEqual(export_vault(self.root, self.conn, archive_path), 1)
        with zipfile.ZipFile(archive_path) as archive:
            self.assertIn(row["file_path"], archive.namelist())
            self.assertIn("manifest.json", archive.namelist())
            self.assertIn("Ship the tested package", archive.read(row["file_path"]).decode())
        with self.assertRaisesRegex(FileExistsError, "refusing to overwrite"):
            export_vault(self.root, self.conn, archive_path)


if __name__ == "__main__":
    unittest.main()
