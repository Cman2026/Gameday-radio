"""During live games (every sport the site covers), listen to each playing team's stream and record what's on.

Reads each stream's "now playing" info (Icecast/Shoutcast metadata, or HLS titles)
and classifies it: "game" (sports talk / play-by-play), "music" (artist - song),
or "unknown". Writes radio-live.json, which the page uses to put a stream that is
carrying the game first and to warn when a station seems to be playing music.
Exits quickly when no games are live. Football results are stored under the stream URL;
other sports under "<sport>|<url>" (see tools/sports.py).
"""
import json, re, time, urllib.request
from concurrent.futures import ThreadPoolExecutor
import sports as SP

UA = {"User-Agent": "Mozilla/5.0 (GamedayRadio game-time check)"}
SPORTS = re.compile(r"football|basketball|hockey|volleyball|baseball|softball|hoops|tip.?off|first pitch|game|vs\.?|\bat\b|kickoff|pre-?game|post-?game|halftime|network|sports|radio|play.by.play|"
                    r"learfield|img|tailgate|touchdown|quarter|espn|fox sports|cbs sports|talk|news", re.I)


def norm(x):
    x = (x or "").lower().replace("&", " and ")
    x = re.sub(r"\bst\.?\b", "state", x)
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", x)).strip()


def now_playing(url, timeout=10):
    """Return (icy_name, title) from the stream, or ('', '') if none is sent."""
    try:
        req = urllib.request.Request(url, headers=UA | {"Icy-MetaData": "1"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            name = r.headers.get("icy-name") or ""
            ct = (r.headers.get("content-type") or "").lower()
            metaint = int(r.headers.get("icy-metaint") or 0)
            if metaint:
                r.read(metaint)
                n = r.read(1)[0] * 16
                meta = r.read(n).decode("utf-8", "ignore") if n else ""
                m = re.search(r"StreamTitle='(.*?)';", meta)
                t = m.group(1) if m else ""
                tx = re.search(r'text="([^"]*)"', t)  # iHeart packs the title into text="..."
                return name, (tx.group(1) if tx else t)
            if "mpegurl" in ct:
                body = r.read(20000).decode("utf-8", "ignore")
                titles = re.findall(r'#EXTINF:[^,]*,(?:.*?title="([^"]*)")?(.*)', body)
                t = next((a or b for a, b in reversed(titles) if (a or b).strip()), "")
                return name, t.strip()
            return name, ""
    except Exception as e:
        return "", f"error: {str(e)[:80]}"


# Out-of-market listeners get a loop message instead of the game (iHeart "Default Geofence Loop Audio").
BLOCKED = re.compile(r"geofence|geo-?block|blackout|not available in your (area|region)|outside (of )?the (market|area)", re.I)
# Automation log titles like "SPONSOR NAME - AD_BREAK" or "--60 PSA - ..." are breaks inside the broadcast, not songs.
AD = re.compile(r"spot ?block|\bspots?\b|commercial|advert|preroll|pre-roll|adw_ad|\bads?\b|ad[_ ]?break|\bpsa\b|\d+ ?psa\b|legal (id|voice)|sponsor", re.I)


def verdict(title, team_words):
    if not title or title.startswith("error"):
        return "unknown"
    if BLOCKED.search(title):
        return "blocked"
    if AD.search(title):
        return "ad"
    if any(w and w in norm(title) for w in team_words) or SPORTS.search(title):
        return "game"
    if " - " in title:  # "Artist - Song"
        return "music"
    return "unknown"


def main():
    live = SP.live()
    if not live:
        print("no live games"); return
    teams = json.load(open("radio.json"))["teams"]
    index = SP.directory_index(teams)
    jobs, seen = [], set()
    for sid, e in live:
        for c in e["competitions"][0]["competitors"]:
            tm = c["team"]
            t = SP.find_team(index, tm)
            if not t: continue
            words = [norm(tm.get("location")), norm(tm.get("name")), norm(tm.get("abbreviation"))]
            for u in SP.streams_for(t, sid)[:4]:
                if (sid, u) in seen: continue
                seen.add((sid, u))
                jobs.append((t["school"], f"{SP.NAMES[sid]}: {e.get('shortName', '')}", u, words, sid))
    jobs = jobs[:500]  # a full basketball night plus football stays well inside the time limit
    with ThreadPoolExecutor(max_workers=16) as ex:
        res = list(ex.map(lambda j: now_playing(j[2]), jobs))
    try:
        state = json.load(open("radio-live.json"))
    except Exception:
        state = {"streams": {}, "log": []}
    # The history log lives in its own file: the page downloads radio-live.json and never reads it.
    try:
        log = json.load(open("radio-live-log.json")).get("log", [])
    except Exception:
        log = []
    log = state.pop("log", []) + log if "log" in state else log
    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    for (school, game, url, words, sid), (name, title) in zip(jobs, res):
        v = verdict(title, words)
        k = SP.key(sid, url)
        prev = state["streams"].get(k, {})
        # A stream that was in an ad the moment we connected probably plays one to every new listener.
        ads = (prev.get("ad_hits", 0) + (1 if v == "ad" else 0))
        checks = prev.get("checks", 0) + 1
        state["streams"][k] = {"school": school, "sport": sid, "verdict": v, "title": title[:120], "icy_name": name[:80], "at": stamp,
                                 "ad_hits": ads, "checks": checks, "preroll": checks >= 2 and ads / checks >= 0.5}
        log.append({"at": stamp, "school": school, "game": game, "url": url, "verdict": v, "title": title[:120]})
    # Forget entries nobody has checked for two days (keeps the file small with many sports).
    cut = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 2 * 86400))
    state["streams"] = {k: v for k, v in state["streams"].items() if v.get("at", "") >= cut}
    state["checked"] = stamp
    json.dump({"log": log[-1200:]}, open("radio-live-log.json", "w"), indent=0)
    json.dump(state, open("radio-live.json", "w"), indent=1)
    music = sorted({f"{school} ({sid})" for (school, _, _, words, sid), (_, title) in zip(jobs, res) if verdict(title, words) == "music"})
    by = {}
    for sid, _ in live: by[sid] = by.get(sid, 0) + 1
    print(f"checked {len(jobs)} streams for {len(live)} live games {by}; possibly music: {', '.join(music) or 'none'}")


if __name__ == "__main__":
    main()
