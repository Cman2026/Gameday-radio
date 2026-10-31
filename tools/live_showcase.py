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
                    r"stretchinternet|surfernetwork|jwplayer\.com/live", re.I)
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
                    soon = False
                    if st == "pre":  # pregame shows start before kickoff
                        try:
                            ko = datetime.datetime.fromisoformat(e["date"].replace("Z", "+00:00"))
                            soon = (ko - datetime.datetime.now(datetime.timezone.utc)).total_seconds() < 45 * 60
                        except Exception:
                            pass
                    if st == "in" or soon:
                        out += [c["team"] for c in e["competitions"][0]["competitors"]]
        except Exception as ex:
            print("scoreboard error", g, ex)
    return out


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
    targets = {}
    for tm in live_teams():
        t = next((index[norm(n)] for n in (tm.get("location"), tm.get("displayName"), tm.get("shortDisplayName")) if norm(n) in index), None)
        if not t:
            continue
        info = src.get(t["school"]) or {}
        # Teams with a station stream are fine; school game feeds change every game, so refresh those.
        if t.get("streams") and not info.get("game_only"):
            continue
        site = info.get("athletics_site")
        if site:
            targets[site.rstrip("/") + "/showcase"] = t
        lp = info.get("listen_page")
        if lp and lp.startswith("http") and "app.link" not in lp:
            targets[lp] = t
    if not targets:
        print("no live teams without radio that have an athletics site on file"); return
    found = sniff(list(targets))
    changed = False
    for url, t in targets.items():
        streams = [u for u in found.get(url, []) if "player_status" not in u and "/v5/" not in u][:3]
        streams = list(dict.fromkeys(streams + (t.get("streams") or [])))[:4]  # newest feed first
        print(t["school"], "->", streams)
        if streams:
            t["streams"] = streams; t["live_only"] = True; changed = True
    if changed:
        json.dump(radio, open("radio.json", "w"), indent=0)


if __name__ == "__main__":
    main()
