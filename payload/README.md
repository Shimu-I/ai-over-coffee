# AI Over Coffee

*The AI world, one morning at a time.*

A quiet, local system that collects AI and ML news from public RSS feeds into
SQLite, picks what matters, and emails you a short editorial PDF each morning.

Built incrementally. Run `cat PATCH_LOG` to see which patches are applied.

## Quick start

```bash
scripts/aoc init-db          # create data/aoc.db and load sources
scripts/aoc status           # short summary
scripts/probe_sources.py     # check which feeds really work from this machine
python3 -m unittest discover -s tests   # run with PYTHONPATH=src
```

## Layout

| Path | Purpose |
|---|---|
| `config/` | `config.yaml`, `sources.yaml` (yours to edit; patches never overwrite) |
| `src/aoc/` | the application, one subpackage per pipeline stage |
| `scripts/` | CLI wrapper and the source probe |
| `tests/` | unit tests (stdlib `unittest`) |
| `data/`, `logs/`, `output/` | runtime state, git-ignored |
| `.env` | secrets, git-ignored; see `.env.example` |

## Updating

Each update arrives as `aoc-patch-NNN.zip`. Unzip it and run:

```bash
bash aoc-patch-NNN/apply.sh ~/ai-over-coffee
```

The script checks patches are applied in order, backs up anything it replaces
(`.patch-backups/NNN/`), never touches `.env`, `data/` or your edited config,
runs the tests, and rolls back automatically if they fail.

## Honest limits

Feeds fail, laptops sleep and sites change. This system makes failures visible
and recovers where it can; it does not promise that no story is ever missed.
