#!/usr/bin/env bash
# AI Over Coffee - patch applier
# Usage: bash apply.sh [TARGET_DIR] [--dry-run] [--no-install] [--commit]
set -euo pipefail

PATCH_ID="001"
REQUIRES="000"
PATCH_TITLE="Project skeleton, config, SQLite schema and source probe"

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PAYLOAD="$HERE/payload"
TARGET="$HOME/ai-over-coffee"
INSTALL=1
COMMIT=0
DRY=0

usage() {
  cat <<'USAGE_EOF'
Usage: bash apply.sh [TARGET_DIR] [options]

  TARGET_DIR     project folder to update (default: ~/ai-over-coffee)
  --dry-run      show what would change, change nothing
  --no-install   skip virtualenv and pip (uses system python3)
  --commit       after a successful apply, run git add/commit/tag for you
                 (creates the repo if needed; never pushes)
  -h, --help     this help
USAGE_EOF
}

say() { printf '%s\n' "$*"; }
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

while [ $# -gt 0 ]; do
  case "$1" in
    --no-install) INSTALL=0 ;;
    --commit)     COMMIT=1 ;;
    --dry-run)    DRY=1 ;;
    -h|--help)    usage; exit 0 ;;
    -*)           printf 'Unknown option: %s\n' "$1" >&2; usage >&2; exit 2 ;;
    *)            TARGET="$1" ;;
  esac
  shift
done
TARGET="${TARGET/#\~/$HOME}"

[ -d "$PAYLOAD" ] || die "payload/ folder not found next to apply.sh"
command -v python3 >/dev/null || die "python3 not found"

# ---- patch ordering -------------------------------------------------------
LEVEL="000"
if [ -f "$TARGET/PATCH_LEVEL" ]; then
  LEVEL="$(tr -d '[:space:]' < "$TARGET/PATCH_LEVEL")"
fi
case "$LEVEL" in ''|*[!0-9]*) die "PATCH_LEVEL in $TARGET is not a number: '$LEVEL'" ;; esac

if [ $((10#$LEVEL)) -ge $((10#$PATCH_ID)) ]; then
  say "Patch $PATCH_ID is already applied (current level $LEVEL). Nothing to do."
  exit 0
fi
if [ $((10#$LEVEL)) -ne $((10#$REQUIRES)) ]; then
  die "Patch $PATCH_ID needs level $REQUIRES, but $TARGET is at level $LEVEL. Apply patches in order."
fi

# ---- plan -----------------------------------------------------------------
mapfile -t FILES < <(cd "$PAYLOAD" && find . -type f | sed 's|^\./||' | LC_ALL=C sort)

EDITABLE=()
if [ -f "$HERE/user_editable.txt" ]; then
  while IFS= read -r line; do
    line="${line%%#*}"
    line="$(printf '%s' "$line" | tr -d '[:space:]')"
    if [ -n "$line" ]; then EDITABLE+=("$line"); fi
  done < "$HERE/user_editable.txt"
fi
is_editable() {
  local f="$1" e
  for e in "${EDITABLE[@]:-}"; do
    if [ "$e" = "$f" ]; then return 0; fi
  done
  return 1
}

for f in "${FILES[@]}"; do
  case "$f" in
    .env|config/config.local.yaml) die "payload tries to ship a protected file: $f" ;;
    data/*|logs/*|output/*)
      [ "$(basename "$f")" = ".gitkeep" ] || die "payload tries to ship a runtime file: $f" ;;
  esac
done

ADD=(); UPD=(); KEEP=(); SAME=0
for f in "${FILES[@]}"; do
  dest="$TARGET/$f"
  if [ ! -e "$dest" ]; then
    ADD+=("$f")
  elif cmp -s "$PAYLOAD/$f" "$dest"; then
    SAME=$((SAME + 1))
  elif is_editable "$f"; then
    KEEP+=("$f")
  else
    UPD+=("$f")
  fi
done

say "Patch $PATCH_ID: $PATCH_TITLE"
say "Target:  $TARGET (current level $LEVEL)"
say "Plan:    ${#ADD[@]} new, ${#UPD[@]} updated (backed up), ${#KEEP[@]} kept as yours (.new saved), $SAME unchanged"
for f in "${UPD[@]:-}";  do [ -z "$f" ] || say "  update  $f"; done
for f in "${KEEP[@]:-}"; do [ -z "$f" ] || say "  keep    $f  (shipped version -> $f.new)"; done
if [ "$DRY" -eq 1 ]; then say "Dry run: nothing changed."; exit 0; fi

# ---- apply (with rollback) ------------------------------------------------
BACKUP="$TARGET/.patch-backups/$PATCH_ID"
CREATED_TARGET=0
if [ ! -e "$TARGET" ]; then CREATED_TARGET=1; fi
mkdir -p "$TARGET"
rm -rf "$BACKUP"
mkdir -p "$BACKUP"
NEWSIDE=()

rollback() {
  say "Rolling back patch $PATCH_ID ..."
  local f
  for f in "${UPD[@]:-}"; do
    if [ -n "$f" ] && [ -e "$BACKUP/$f" ]; then cp -p "$BACKUP/$f" "$TARGET/$f"; fi
  done
  for f in "${ADD[@]:-}";     do [ -z "$f" ] || rm -f "$TARGET/$f"; done
  for f in "${NEWSIDE[@]:-}"; do [ -z "$f" ] || rm -f "$TARGET/$f.new"; done
  # A folder this run created from nothing is removed entirely on failure.
  if [ "$CREATED_TARGET" -eq 1 ] && [ -n "$TARGET" ] && [ "$TARGET" != "/" ] && [ "$TARGET" != "$HOME" ]; then
    rm -rf "$TARGET"
  fi
  say "Rolled back. Your files are as they were before this patch."
}
fail() { say "$*"; rollback; exit 1; }

install_file() {
  local src="$1" dest="$2"
  mkdir -p "$(dirname "$dest")"
  cp "$src" "$dest"
  if [ -x "$src" ]; then chmod +x "$dest"; fi
}

for f in "${UPD[@]:-}"; do
  [ -n "$f" ] || continue
  mkdir -p "$BACKUP/$(dirname "$f")"
  cp -p "$TARGET/$f" "$BACKUP/$f" || fail "Could not back up $f"
done
for f in "${ADD[@]:-}" "${UPD[@]:-}"; do
  [ -n "$f" ] || continue
  install_file "$PAYLOAD/$f" "$TARGET/$f" || fail "Could not write $f"
done
for f in "${KEEP[@]:-}"; do
  [ -n "$f" ] || continue
  NEWSIDE+=("$f")
  install_file "$PAYLOAD/$f" "$TARGET/$f.new" || fail "Could not write $f.new"
done

# ---- dependencies ---------------------------------------------------------
PYBIN="python3"
if [ "$INSTALL" -eq 1 ] && [ -f "$TARGET/requirements.txt" ]; then
  if [ ! -x "$TARGET/.venv/bin/python" ]; then
    say "Creating virtualenv (.venv) ..."
    python3 -m venv "$TARGET/.venv" || fail "Could not create the virtualenv (is python3-venv installed?)"
  fi
  PYBIN="$TARGET/.venv/bin/python"
  WANT="$(sha256sum "$TARGET/requirements.txt" | cut -d' ' -f1)"
  HAVE=""
  if [ -f "$TARGET/.venv/.requirements.sha256" ]; then HAVE="$(cat "$TARGET/.venv/.requirements.sha256")"; fi
  if [ "$WANT" != "$HAVE" ]; then
    say "Installing Python dependencies ..."
    "$PYBIN" -m pip install --quiet --disable-pip-version-check -r "$TARGET/requirements.txt" \
      || fail "pip install failed (network problem?)"
    printf '%s\n' "$WANT" > "$TARGET/.venv/.requirements.sha256"
  fi
elif [ -x "$TARGET/.venv/bin/python" ]; then
  PYBIN="$TARGET/.venv/bin/python"
fi

# ---- tests ----------------------------------------------------------------
say "Running tests ..."
TESTLOG="$(mktemp)"
if (cd "$TARGET" && PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src "$PYBIN" -m unittest discover -s tests >"$TESTLOG" 2>&1); then
  tail -n 4 "$TESTLOG"
  rm -f "$TESTLOG"
else
  cat "$TESTLOG"; rm -f "$TESTLOG"
  fail "Tests failed, so the patch was not kept."
fi

# ---- record ---------------------------------------------------------------
printf '%s\n' "$PATCH_ID" > "$TARGET/PATCH_LEVEL"
printf '%s  %s  %s\n' "$PATCH_ID" "$(date +%F)" "$PATCH_TITLE" >> "$TARGET/PATCH_LOG"
cp "$HERE/COMMIT_MSG.txt" "$BACKUP/COMMIT_MSG.txt"
SUBJECT="$(head -n1 "$HERE/COMMIT_MSG.txt")"

say ""
say "Patch $PATCH_ID applied. Project is now at level $PATCH_ID."
if [ "${#KEEP[@]}" -gt 0 ]; then
  say "Note: you had edited some files, so they were kept. Compare with the .new copies if you want the shipped changes."
fi
say ""
say "Try it:"
say "  cd $TARGET"
say "  scripts/aoc init-db"
say "  scripts/aoc status"
say "  scripts/probe_sources.py        # checks every feed from this machine"
say ""
say "Commit it:"
if [ ! -d "$TARGET/.git" ]; then say "  git init -b main      # first time only"; fi
say "  git add -A"
say "  git commit -F .patch-backups/$PATCH_ID/COMMIT_MSG.txt"
say "  git tag -a patch-$PATCH_ID -m \"$SUBJECT\""

if [ "$COMMIT" -eq 1 ]; then
  say ""
  command -v git >/dev/null || { say "git not found; skipping --commit."; exit 0; }
  cd "$TARGET"
  if ! git config user.name >/dev/null || ! git config user.email >/dev/null; then
    say "git user.name / user.email not set; skipping --commit. Set them, then run the commit commands above."
    exit 0
  fi
  if [ ! -d .git ]; then git init -q -b main; fi
  git add -A
  git commit -q -F ".patch-backups/$PATCH_ID/COMMIT_MSG.txt"
  git tag -a "patch-$PATCH_ID" -m "$SUBJECT"
  say "Committed and tagged patch-$PATCH_ID (not pushed)."
fi
