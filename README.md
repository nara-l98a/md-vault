# md-vault CLI

A private, local-first Markdown notebook for collecting searchable knowledge. It stores readable `.md` files in your vault and maintains a SQLite catalogue with full-text search (FTS5 when available; a built-in `LIKE` search fallback otherwise). Tags, edit timestamps, exact-tag filtering, and index rebuilding are included. It makes no network requests and requires no third-party runtime packages.

## Requirements

- Python 3.10 or newer
- SQLite is included with Python; FTS5 is optional

## Install

```bash
git clone https://github.com/nara-l98a/md-vault-cli.git
cd md-vault-cli
python3 -m venv .venv
. .venv/bin/activate
pip install .
```

From a checkout without installing: `PYTHONPATH=src python -m mdvault --help`.

## Quick start

```bash
# Create a vault (also happens automatically when adding the first note).
mdvault --vault ~/Notes/vault init

# Add a note. Tags can be entered as words or comma-separated values.
mdvault --vault ~/Notes/vault add \
  --title "Incident response checklist" \
  --body "Confirm scope, preserve logs, assign an incident lead, and record decisions." \
  --tags security operations

# Search every title, body, and tag; list/show notes and available tags.
mdvault --vault ~/Notes/vault search "incident logs"
mdvault --vault ~/Notes/vault list --tag security
mdvault --vault ~/Notes/vault show 1
mdvault --vault ~/Notes/vault tags

# Update selected fields, or rebuild the catalogue from the Markdown files.
mdvault --vault ~/Notes/vault update 1 --body "Updated response checklist with a recovery review."
mdvault --vault ~/Notes/vault reindex

# Remove a note from the catalogue and delete its managed Markdown file.
mdvault --vault ~/Notes/vault delete 1
```

Example search result:

```text
[1] Incident response checklist  (tags: security, operations)
    Confirm scope, preserve logs, assign an incident lead, and record decisions.
    notes/incident-response-checklist-000001.md
```

## Vault layout and data

```text
vault/
├── .mdvault.sqlite3    # searchable index and metadata
└── notes/
    └── topic-000001.md # readable Markdown files
```

By default, the vault is `~/Documents/md-vault`. Select a different location with the global `--vault PATH` option (before the command) or the `MDVAULT_HOME` environment variable. Notes are ordinary UTF-8 Markdown files with a title heading and small HTML-comment metadata markers. Keep the SQLite catalogue and Markdown files together. If you edit note files outside md-vault, run `reindex` to refresh the catalogue. Reindex accepts md-vault-managed Markdown notes and stops without replacing the existing catalogue if it encounters an unmanaged `.md` file in `notes/`.

## Commands

| Command | Purpose |
|---|---|
| `init` | Create the vault directory and index |
| `add --title TITLE --body TEXT [--tags TAG ...]` | Add a note |
| `list [--tag TAG] [--limit N]` | List recent notes; tag filtering is exact |
| `search QUERY [--limit N]` | Search title, body, and tags (all query terms must match) |
| `show ID` | Show the full note and metadata |
| `update ID [--title TITLE] [--body TEXT] [--tags TAG ...]` | Update selected fields |
| `delete ID` | Delete a note and its Markdown file |
| `tags` | List tags and their note counts |
| `reindex` | Rebuild the SQLite catalogue and full-text index from note files |

## Development and tests

```bash
python -m unittest discover -s tests -v
```

Tests use temporary vaults and do not touch your personal notes.

## Privacy

Your note contents remain on your machine. The SQLite database may include a search index of your notes; back up the entire vault and avoid committing private vault data to source control.

## License

MIT. See [LICENSE](LICENSE).
