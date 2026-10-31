"""For live games where a team has no radio stream on file, open the school's
athletics site live-audio page in a headless browser, capture the game audio
stream, and add it to radio.json. Many schools only stream games on their own
site, and those streams exist only while the game is on.
"""
import datetime, json, re, subprocess, sys, urllib.request

UA = {"User-Agent": "Mozilla/5.0 (GamedayRadio live audio finder)"}
SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/football/college-football/scoreboard?groups={}&limit=400"
STREAM = re.compile(r"\.(mp3|aac|m3u8)(\?|$)|streamtheworld|amperwave\.net/(manifest|direct|playlist)|securenetsystems\.net/[A-Z]|"
                    r"ihrhls|streamguys1?\.com|cdnstream1|streamon\.fm|radio\.co|zeno\.fm|mixlr|lightningstream|liveradio|"
                    r"stretchinternet|surfernetwork|jwplayer\.com/live|leanstream|leanplayer\.com/.*(stream|live)|streamon|cloudfront\.net/.*\.(m3u8|aac|mp3)", re.I)
BAD = re.compile(r"google|adsrvr|doubleclick|2mdn|\.js(\?|$)|\.css|favicon|assets|fonts|analytics|silent\.mp3|podtrac|omny|/ads/", re.I)


def norm(x):
    x = (x or "").lower().replace("&", " and ")
    x = re.sub(r"\bst\.?\b", "state", x)
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", x)).strip()


def live_teams():
    out = []
    for g in (80, 81):
        try:
            with urllib.request.urlopen(urllib.request.Request(SCOREBOARD.format(g), headers=UA), timeout=20) as r:
                for e in json.loads(r.read()).get("events", []):
                    st = e.get("status", {}).get("type", {}).get("state")
                    soon, mins = False, 0
                    if st == "pre":  # pregame shows start before kickoff
                        try:
                            ko = datetime.datetime.fromisoformat(e["date"].replace("Z", "+00:00"))
                            mins = (ko - datetime.datetime.now(datetime.timezone.utc)).total_seconds() / 60
                            soon = mins < 180
                        except Exception:
                            pass
                    if st == "in" or soon:
                        out += [dict(c["team"], _mins=mins) for c in e["competitions"][0]["competitors"]]
        except Exception as ex:
            print("scoreboard error", g, ex)
    return out


def sidearm_audio(site):
    """SIDEARM athletics sites list their live events in a JSON feed; free audio events
    carry the stream URL directly (often a Leanstream or StreamGuys mount)."""
    out = []
    url = site.rstrip("/") + "/services/allaccess.ashx/media/get?type=Live&count=12&tab=1&pageSize=12"
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA | {"Accept": "application/json"}), timeout=15) as r:
            data = json.loads(r.read())
        if isinstance(data, str):
            data = json.loads(data)
    except Exception as ex:
        print("allaccess error", site, str(ex)[:80]); return out
    now = datetime.datetime.now(datetime.timezone.utc)
    for ev in data if isinstance(data, list) else []:
        if (ev.get("sport_shortname") or "").lower() != "football" or (ev.get("format") or "").lower() != "audio":
            continue
        if ev.get("premium") or ev.get("app_exclusive") or ev.get("free") is False:
            continue
        try:
            start = datetime.datetime.fromisoformat(ev["date_utc"].replace("Z", "+00:00"))
            end = datetime.datetime.fromisoformat((ev.get("dateend_utc") or ev["date_utc"]).replace("Z", "+00:00"))
            if not (start - datetime.timedelta(hours=2) <= now <= end + datetime.timedelta(hours=1)):
                continue
        except Exception:
            continue
        out += [u for u in (ev.get("formats") or {}).values() if isinstance(u, str) and u.startswith("http")]
    return list(dict.fromkeys(out))


def sniff(urls):
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", "playwright"], check=True)
    subprocess.run([sys.executable, "-m", "playwright", "install", "--with-deps", "chromium"], check=True, stdout=subprocess.DEVNULL)
    from playwright.sync_api import sync_playwright
    found = {}
    with sync_playwright() as p:
        b = p.chromium.launch(args=["--autoplay-policy=no-user-gesture-required"])
        for url in urls:
            hits = []
            ctx = b.new_context(user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36")
            ctx.on("request", lambda r: hits.append(r.url) if (STREAM.search(r.url) and not BAD.search(r.url)) else None)
            page = ctx.new_page()
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(5000)
                # SIDEARM showcase pages list live events; open audio/football ones.
                for sel in ["a:has-text('Football'):has-text('Audio')", "a[href*='type=Live']", "a:has-text('Listen')",
                            "[aria-label*='play' i]", "button:has-text('Play')"]:
                    try:
                        el = page.locator(sel).first
                        if el.count() and el.is_visible():
                            el.click(timeout=3000); page.wait_for_timeout(6000)
                    except Exception:
                        pass
            except Exception as ex:
                print("open error", url, ex)
            found[url] = list(dict.fromkeys(hits))
            ctx.close()
        b.close()
    return found


def main():
    radio = json.load(open("radio.json"))
    src = {s["school"]: s for s in json.load(open("tools/radio-sources.json"))}
    index = {}
    for t in radio["teams"]:
        for n in [t.get("school")] + (t.get("names") or []):
            if n: index.setdefault(norm(n), t)
    targets, feed_changed = {}, []
    for tm in live_teams():
        t = next((index[norm(n)] for n in (tm.get("location"), tm.get("displayName"), tm.get("shortDisplayName")) if norm(n) in index), None)
        if not t:
            continue
        info = src.get(t["school"]) or {}
        site = info.get("athletics_site")
        # Teams with a station stream still get the school's official audio feed added (it's the
        # actual broadcast and isn't blocked outside the station's area); no browser needed for them.
        if t.get("streams") and not info.get("game_only"):
            if site:
                got = sidearm_audio(site)
                if got:
                    t["streams"] = list(dict.fromkeys(got + t["streams"]))[:5]; t["live_only"] = True
                    feed_changed.append(t["school"])
            continue
        t["_mins"] = min(t.get("_mins", 999), tm.get("_mins", 0))
        if site:
            targets[site.rstrip("/") + "/showcase"] = t
        lp = info.get("listen_page")
        if lp and lp.startswith("http") and "app.link" not in lp:
            targets[lp] = t
    print("official feeds added for:", ", ".join(feed_changed) or "none")
    if not targets:
        print("no live teams without radio that have an athletics site on file")
        if feed_changed:
            for t in radio["teams"]: t.pop("_mins", None)
            json.dump(radio, open("radio.json", "w"), indent=0)
        return
    # Fast path: the SIDEARM live-events feed names the audio stream outright.
    changed = bool(feed_changed)
    for url, t in list(targets.items()):
        if url not in targets:
            continue
        site = (src.get(t["school"]) or {}).get("athletics_site")
        got = sidearm_audio(site) if site and url.endswith("/showcase") else []
        if got:
            print(t["school"], "-> (feed)", got)
            t["streams"] = list(dict.fromkeys(got + (t.get("streams") or [])))[:4]; t["live_only"] = True; changed = True
            targets = {u: x for u, x in targets.items() if x is not t}
    # Opening pages in a browser is slow, so only do it close to kickoff.
    targets = {u: x for u, x in targets.items() if x.get("_mins", 0) < 45}
    found = sniff(list(targets)) if targets else {}
    for url, t in targets.items():
        streams = [u for u in found.get(url, []) if "player_status" not in u and "/v5/" not in u][:3]
        streams = list(dict.fromkeys(streams + (t.get("streams") or [])))[:4]  # newest feed first
        print(t["school"], "->", streams)
        if streams:
            t["streams"] = streams; t["live_only"] = True; changed = True
    for t in radio["teams"]:
        t.pop("_mins", None)
    if changed:
        json.dump(radio, open("radio.json", "w"), indent=0)


if __name__ == "__main__":
    main()
