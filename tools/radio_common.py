"""Shared rules for the radio directory (used by the resolver, the game-time check and publish.sh).

- bad_streams: per-team list in tools/radio-sources.json of stream URLs (or substrings) that must
  never be offered, even if a lookup finds them again (wrong station, music station, ...).
- game feeds: streams the game-time check pulls from a school's own site for today's game. They
  are listed in "game_feeds" with a timestamp, kept at the front of "streams" while fresh, and
  dropped once they are a day old (the links change every game).
"""
import datetime, json, re

FEED_TTL_H = 16


def load_sources(path="tools/radio-sources.json"):
    try:
        return {s["school"]: s for s in json.load(open(path))}
    except Exception:
        return {}


def is_bad(school, url, sources):
    for b in (sources.get(school) or {}).get("bad_streams") or []:
        if b and b.lower() in url.lower():
            return True
    return False


def feeds_fresh(team, now=None):
    at = team.get("game_feeds_at")
    if not at or not team.get("game_feeds"):
        return False
    try:
        t = datetime.datetime.fromisoformat(at.replace("Z", "+00:00"))
    except Exception:
        return False
    now = now or datetime.datetime.now(datetime.timezone.utc)
    return (now - t).total_seconds() < FEED_TTL_H * 3600


def set_feeds(team, feeds, stamp):
    """Make `feeds` today's game feeds for the team: first in line, replacing yesterday's."""
    old = set(team.get("game_feeds") or [])
    rest = [u for u in (team.get("streams") or []) if u not in old and u not in feeds]
    team["game_feeds"] = list(dict.fromkeys(feeds))
    team["game_feeds_at"] = stamp
    team["streams"] = list(dict.fromkeys(list(feeds) + rest))[:6]
    team["live_only"] = True


def clean(team, sources):
    """Drop bad and stale-feed streams from a team entry (in place)."""
    school = team.get("school", "")
    if not feeds_fresh(team):
        old = set(team.get("game_feeds") or [])
        team["streams"] = [u for u in (team.get("streams") or []) if u not in old]
        team.pop("game_feeds", None); team.pop("game_feeds_at", None)
        if team.get("live_only") and not team["streams"]:
            team["live_only"] = False
    team["streams"] = [u for u in (team.get("streams") or []) if not is_bad(school, u, sources)]
    team["game_feeds"] = [u for u in (team.get("game_feeds") or []) if not is_bad(school, u, sources)] or team.get("game_feeds")
    if team.get("game_feeds") == []:
        team.pop("game_feeds", None)
    return team


def merge_into(current, new, sources, feeds_only=False):
    """Merge a job's radio.json (`new`) onto the current one (`current`), both {teams:[...]}.
    feeds_only: only carry over game feeds the job found (game-time check); otherwise the job's
    tested station streams replace the current ones, keeping today's game feeds in front."""
    cur = {t["school"]: t for t in current["teams"]}
    for n in new["teams"]:
        t = cur.get(n["school"])
        if not t:
            if not feeds_only:
                current["teams"].append(n)
            continue
        if feeds_fresh(n) and (not feeds_fresh(t) or n.get("game_feeds_at", "") >= t.get("game_feeds_at", "")):
            set_feeds(t, n["game_feeds"], n["game_feeds_at"])
        if not feeds_only:
            feeds = t.get("game_feeds") if feeds_fresh(t) else []
            station = [u for u in (n.get("streams") or []) if u not in (n.get("game_feeds") or [])]
            for k in ("network", "flagship", "listen_page", "conference", "calls", "game_only", "no_radio", "notes", "misses", "miss_day", "last_ok", "names"):
                if k in n:
                    t[k] = n[k]
            t["streams"] = list(dict.fromkeys(list(feeds or []) + station))[:6]
    for t in current["teams"]:
        clean(t, sources)
    return current
