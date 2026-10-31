#!/usr/bin/env bash
# Commit job output files and push, retrying on top of the newest main if
# another job pushed first. Usage: tools/publish.sh "message" file1 [file2 ...]
set -u
msg="$1"; shift
git config user.name "github-actions[bot]"
git config user.email "41898699+github-actions[bot]@users.noreply.github.com"
tmp=$(mktemp -d)
for f in "$@"; do [ -f "$f" ] && cp "$f" "$tmp/$(basename "$f")"; done
for attempt in 1 2 3 4 5; do
  git fetch -q origin main && git reset -q --hard origin/main
  for f in "$@"; do
    [ -f "$tmp/$(basename "$f")" ] || continue
    if [ "$f" = "radio.json" ]; then
      # Merge the job's radio.json onto whatever is on main now, so two jobs (or a hand edit)
      # can't wipe out each other's changes. Game-time jobs only carry over the game feeds they
      # found; the resolver replaces the tested station streams but keeps today's feeds in front.
      python3 - "$tmp/radio.json" "${MERGE_LIVE_ONLY:-}" <<'PY'
import json, sys
sys.path.insert(0, "tools")
from radio_common import merge_into, load_sources
new = json.load(open(sys.argv[1]))
cur = json.load(open("radio.json"))
out = merge_into(cur, new, load_sources(), feeds_only=bool(sys.argv[2]))
if not sys.argv[2]:
    out["built"] = new.get("built", out.get("built"))
json.dump(out, open("radio.json", "w"), indent=0)
PY
    else
      cp "$tmp/$(basename "$f")" "$f"
    fi
  done
  for f in "$@"; do [ -f "$f" ] && git add "$f"; done
  if git diff --cached --quiet; then echo "nothing to publish"; exit 0; fi
  git commit -q -m "$msg"
  if git push -q origin HEAD:main; then echo "published on attempt $attempt"; exit 0; fi
  sleep $((attempt * 5))
done
echo "could not publish after 5 attempts"; exit 1
