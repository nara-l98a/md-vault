# md-vault CLI

A private, local-first Markdown notebook for collecting searchable knowledge. It stores readable `.md` files in your vault and maintains a SQLite catalogue with full-text search (FTS5 when available; a built-in `LIKE` search fallback otherwise). Tags, edit timestamps, exact-tag filtering, and index rebuilding are included. It makes no network requests and requires no third-party runtime packages.

## Requirements

- Python 3.10 or newer
- SQLite is included with Python; FTS5 is optional

## Install

```bash
git clone https://github.com/nara-l98a/md-vault.git
cd md-vault
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

# Export managed Markdown files plus a metadata manifest; existing archives are not overwritten.
mdvault --vault ~/Notes/vault export ~/Backups/notes-2026-04.zip

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
| `export FILE.zip` | Create a ZIP of managed Markdown notes and a JSON metadata manifest; refuses to overwrite |

## Development and tests

```bash
python -m pip install -e .
python -m unittest discover -s tests -v
```

Tests use temporary vaults and do not touch your personal notes.

## Privacy

Your note contents remain on your machine. The SQLite database may include a search index of your notes; back up the entire vault and avoid committing private vault data to source control.

## License

MIT. See [LICENSE](LICENSE).


## 中文使用说明

`mdvault` 是一个只在本机读写的 Markdown 笔记库：笔记内容保存在 `notes/`，SQLite 仅作为可重建的搜索索引。程序不发起网络请求，也不会上传笔记。

```bash
# 使用中文标题、正文和标签
mdvault --vault ~/Notes/vault add \
  --title "发布检查清单" \
  --body "确认测试、备份和回滚方案。" \
  --tags 发布 运维

# 外部编辑 Markdown 后重建索引
mdvault --vault ~/Notes/vault reindex
```

导出会创建一个新的 ZIP（若目标已存在则拒绝覆盖）。索引中的笔记路径必须位于 vault 内；发现未管理的 Markdown 或路径逃逸时，`reindex`/`export` 会报错而不继续操作。
