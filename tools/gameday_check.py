"""During live FBS games, listen to each playing team's stream and record what's on.

Reads each stream's "now playing" info (Icecast/Shoutcast metadata, or HLS titles)
and classifies it: "game" (sports talk / play-by-play), "music" (artist - song),
or "unknown". Writes radio-live.json, which the page uses to put a stream that is
carrying the game first and to warn when a station seems to be playing music.
Exits quickly when no FBS games are live.
"""
import json, re, time, urllib.request
from concurrent.futures import ThreadPoolExecutor

UA = {"User-Agent": "Mozilla/5.0 (GamedayRadio game-time check)"}
ESPN = "https://site.api.espn.com/apis/site/v2/sports/football/college-football/scoreboard?groups=80&limit=400"
SPORTS = re.compile(r"football|game|vs\.?|\bat\b|kickoff|pre-?game|post-?game|halftime|network|sports|radio|play.by.play|"
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


AD = re.compile(r"spot ?block|\bspots?\b|commercial|advert|preroll|pre-roll|adw_ad|\bads?\b|sponsor", re.I)


def verdict(title, team_words):
    if not title or title.startswith("error"):
        return "unknown"
    if AD.search(title):
        return "ad"
    if any(w and w in norm(title) for w in team_words) or SPORTS.search(title):
        return "game"
    if " - " in title:  # "Artist - Song"
        return "music"
    return "unknown"


def main():
    with urllib.request.urlopen(urllib.request.Request(ESPN, headers=UA), timeout=20) as r:
        events = json.loads(r.read()).get("events", [])
    live = [e for e in events if e.get("status", {}).get("type", {}).get("state") == "in"]
    if not live:
        print("no live FBS games"); return
    teams = json.load(open("radio.json"))["teams"]
    index = {}
    for t in teams:
        for n in [t.get("school")] + (t.get("names") or []):
            if n: index.setdefault(norm(n), t)
    jobs = []
    for e in live:
        for c in e["competitions"][0]["competitors"]:
            tm = c["team"]
            t = next((index[norm(n)] for n in (tm.get("location"), tm.get("displayName"), tm.get("shortDisplayName")) if norm(n) in index), None)
            if not t: continue
            words = [norm(tm.get("location")), norm(tm.get("name")), norm(tm.get("abbreviation"))]
            for u in t.get("streams") or []:
                jobs.append((t["school"], e.get("shortName", ""), u, words))
    with ThreadPoolExecutor(max_workers=16) as ex:
        res = list(ex.map(lambda j: now_playing(j[2]), jobs))
    try:
        state = json.load(open("radio-live.json"))
    except Exception:
        state = {"streams": {}, "log": []}
    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    for (school, game, url, words), (name, title) in zip(jobs, res):
        v = verdict(title, words)
        prev = state["streams"].get(url, {})
        # A stream that was in an ad the moment we connected probably plays one to every new listener.
        ads = (prev.get("ad_hits", 0) + (1 if v == "ad" else 0))
        checks = prev.get("checks", 0) + 1
        state["streams"][url] = {"school": school, "verdict": v, "title": title[:120], "icy_name": name[:80], "at": stamp,
                                 "ad_hits": ads, "checks": checks, "preroll": checks >= 2 and ads / checks >= 0.5}
        state["log"].append({"at": stamp, "school": school, "game": game, "url": url, "verdict": v, "title": title[:120]})
    state["log"] = state["log"][-600:]
    state["checked"] = stamp
    json.dump(state, open("radio-live.json", "w"), indent=1)
    music = sorted({school for (school, _, _, words), (_, title) in zip(jobs, res) if verdict(title, words) == "music"})
    print(f"checked {len(jobs)} streams for {len(live)} live games; possibly music: {', '.join(music) or 'none'}")


if __name__ == "__main__":
    main()
