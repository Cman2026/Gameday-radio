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
    if [ "$f" = "radio.json" ] && [ -n "${MERGE_LIVE_ONLY:-}" ]; then
      # game-time job: only carry over streams it found for teams that had none
      python3 - "$tmp/radio.json" <<'PY'
import json, sys
new = {t["school"]: t for t in json.load(open(sys.argv[1]))["teams"]}
cur = json.load(open("radio.json"))
for t in cur["teams"]:
    n = new.get(t["school"])
    if n and n.get("live_only") and (not t.get("streams") or t.get("game_only")):
        t["streams"], t["live_only"] = n["streams"], True
json.dump(cur, open("radio.json", "w"), indent=0)
PY
    else
      cp "$tmp/$(basename "$f")" "$f"
    fi
  done
  git add "$@" 2>/dev/null
  if git diff --cached --quiet; then echo "nothing to publish"; exit 0; fi
  git commit -q -m "$msg"
  if git push -q origin HEAD:main; then echo "published on attempt $attempt"; exit 0; fi
  sleep $((attempt * 5))
done
echo "could not publish after 5 attempts"; exit 1
