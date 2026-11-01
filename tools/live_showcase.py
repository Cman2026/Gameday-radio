"""For live games (every sport the site covers) where a team has no radio stream on file, open the school's
athletics site live-audio page in a headless browser, capture the game audio
stream, and add it to radio.json. Many schools only stream games on their own
site, and those streams exist only while the game is on.
"""
import datetime, json, re, subprocess, sys, time, urllib.request
from radio_common import is_bad, set_feeds, clean, feeds_fresh
import sports as SP

UA = {"User-Agent": "Mozilla/5.0 (GamedayRadio live audio finder)"}
STREAM = re.compile(r"\.(mp3|aac|m3u8)(\?|$)|streamtheworld|amperwave\.net/(manifest|direct|playlist)|ice\d*\.securenetsystems\.net/|"
                    r"ihrhls|streamguys1?\.com|caster\.fm|cdnstream1|streamon\.fm|radio\.co|zeno\.fm|mixlr|lightningstream|liveradio|"
                    r"stretchinternet|surfernetwork|jwplayer\.com/live|leanstream|leanplayer\.com/.*(stream|live)|streamon|cloudfront\.net/.*\.(m3u8|aac|mp3)", re.I)
BAD = re.compile(r"google|adsrvr|doubleclick|2mdn|\.js(\?|$)|\.css|favicon|assets|fonts|analytics|silent\.mp3|podtrac|omny|/ads/", re.I)


# Things a page loads that aren't a live audio stream: images, video-on-demand manifests,
# archived recordings, blob: URLs and the player page itself.
NOT_LIVE = re.compile(r"\.(png|jpe?g|gif|svg|webp|ico)(\?|$)|^blob:|jwplayer\.com/manifests/|jwpsrv\.com|"
                      r"portal\.stretchinternet\.com/[^/]+/?$|cloudfront\.net/.*-hls/master|/gfx/|thumbnail|poster|"
                      r"\.(cfm|php|aspx?|json|xml|html?)(\?|$)|/advertising/|ad_campaign|stationSettings", re.I)


def norm(x):
    x = (x or "").lower().replace("&", " and ")
    x = re.sub(r"\bst\.?\b", "state", x)
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", x)).strip()


def live_teams():
    """Teams in live games, or games starting within 3 hours (pregame shows start early), any sport."""
    out = []
    for sid, e in SP.scoreboards():
        st = e.get("status", {}).get("type", {}).get("state")
        soon, mins = False, 0
        if st == "pre":
            try:
                ko = datetime.datetime.fromisoformat(e["date"].replace("Z", "+00:00"))
                mins = (ko - datetime.datetime.now(datetime.timezone.utc)).total_seconds() / 60
                soon = mins < 180
            except Exception:
                pass
        if st == "in" or soon:
            out += [dict(c["team"], _mins=mins, _sport=sid) for c in e["competitions"][0]["competitors"]]
    # Football first (it's the busiest and was here first), then the rest; soonest games first.
    order = list(SP.SPORTS)
    return sorted(out, key=lambda t: (order.index(t["_sport"]), t["_mins"]))


def sidearm_audio(site, sport="fb"):
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
        short = (ev.get("sport_shortname") or "").strip().replace(" ", "")
        if (ev.get("format") or "").lower() != "audio":
            continue
        if not SP.SIDEARM[sport].match(short):
            if short: SEEN_SHORT.add(short)
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


SEEN_SHORT = set()


def leanplayer_audio(page_url, sport="fb"):
    """LEANplayer pages (school audio players) list today's events in a signed XML file."""
    try:
        html = urllib.request.urlopen(urllib.request.Request(page_url, headers=UA), timeout=15).read().decode("utf-8", "ignore")
        m = re.search(r"""https?://[^"'\s<>]+live_events[^"'\s<>]+\.xml[^"'\s<>]*""", html) or re.search(r"""/uploads/xml/[^"'\s<>]+\.xml[^"'\s<>]*""", html)
        if not m:
            return []
        xu = m.group(0).replace("&amp;", "&")
        if xu.startswith("/"):
            xu = page_url.rstrip("/") + xu
        xml = urllib.request.urlopen(urllib.request.Request(xu, headers=UA), timeout=15).read().decode("utf-8", "ignore")
        print("leanplayer xml", page_url, xml[:600].replace("\n", " "))
        urls = re.findall(r"""https?://[^"'\s<>\]]+""", xml)
        urls = [u for u in dict.fromkeys(urls) if re.search(r"leanstream|\.m3u8|\.mp3|\.aac|/live", u, re.I) and not NOT_LIVE.search(u)]
        # Streams tagged for this sport; untagged ones only if nothing is tagged at all.
        mine = [u for u in urls if re.search(rf"sport=({SP.LEAN[sport]})\b", u, re.I)]
        tagged = [u for u in urls if re.search(r"sport=\w+", u, re.I)]
        return (mine or ([] if tagged else urls))[:3]
    except Exception as ex:
        print("leanplayer error", page_url, str(ex)[:100]); return []


def sniff(urls, labels=None):
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
                lab = (labels or {}).get(url, "Football")
                for sel in [f"a:has-text('{lab}'):has-text('Audio')", "a[href*='type=Live']", "a:has-text('Listen')",
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


CARRIES = SP.load_carries()
STAMP = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def main():
    radio = json.load(open("radio.json"))
    src = {s["school"]: s for s in json.load(open("tools/radio-sources.json"))}
    for t in radio["teams"]:
        clean(t, src)  # drop bad streams and yesterday's game feeds
    index = {}
    for t in radio["teams"]:
        for n in [t.get("school")] + (t.get("names") or []):
            if n: index.setdefault(norm(n), t)
    targets, feed_changed, done = {}, [], set()
    sport_of = {}  # school -> the sport we're finding audio for this run
    for tm in live_teams():
        t = SP.find_team(index, tm)
        if not t or t["school"] in done:
            continue
        done.add(t["school"])
        sid = tm["_sport"]
        sport_of[t["school"]] = sid
        info = src.get(t["school"]) or {}
        site = info.get("athletics_site")
        have = SP.streams_for(t, sid) if sid != "fb" else t.get("streams")
        # Volleyball, baseball, softball: the main station doesn't count until it's known to carry the sport,
        # so these teams always get the full school-site search (browser included).
        if not SP.station_carries(t, sid, CARRIES):
            have = [u for u in have if u in (t.get("game_feeds") or [])]
        # Teams with a station stream still get the school's official audio feed added (it's the
        # actual broadcast and isn't blocked outside the station's area); no browser needed for them.
        if have and not info.get("game_only"):
            if site:
                got = [u for u in sidearm_audio(site, sid) if not is_bad(t["school"], u, src)]
                if got:
                    set_feeds(t, got, STAMP, sid)
                    feed_changed.append(f"{t['school']} ({sid})")
            continue
        t["_mins"] = min(t.get("_mins", 999), tm.get("_mins", 0))
        t["_sport"] = sid
        if site:
            targets[site.rstrip("/") + "/showcase"] = t
        lp = info.get("listen_page")
        if lp and lp.startswith("http") and "app.link" not in lp:
            targets[lp] = t
    print("official feeds added for:", ", ".join(feed_changed) or "none")
    if not targets:
        print("no live teams without radio that have an athletics site on file")
        for t in radio["teams"]: t.pop("_mins", None); t.pop("_sport", None)
        json.dump(radio, open("radio.json", "w"), indent=0)
        return
    # Fast path: the SIDEARM live-events feed names the audio stream outright.
    changed = bool(feed_changed)
    for url, t in list(targets.items()):
        if url not in targets:
            continue
        site = (src.get(t["school"]) or {}).get("athletics_site")
        got = sidearm_audio(site, t.get("_sport", "fb")) if site and url.endswith("/showcase") else []
        got = [u for u in got if not is_bad(t["school"], u, src)]
        if got:
            print(t["school"], t.get("_sport"), "-> (feed)", got)
            set_feeds(t, got, STAMP, t.get("_sport", "fb")); changed = True
            targets = {u: x for u, x in targets.items() if x is not t}
    for url, t in list(targets.items()):
        if "leanplayer.com" in url:
            got = [u for u in leanplayer_audio(url, t.get("_sport", "fb")) if not is_bad(t["school"], u, src)]
            if got:
                print(t["school"], t.get("_sport"), "-> (leanplayer)", got)
                set_feeds(t, got, STAMP, t.get("_sport", "fb")); changed = True
                targets = {u: x for u, x in targets.items() if x is not t}
    # Opening pages in a browser is slow, so only do it close to kickoff.
    targets = {u: x for u, x in targets.items() if x.get("_mins", 0) < 45}
    # A basketball night can have dozens of these; cap the browser work per run (football first).
    targets = dict(list(targets.items())[:24])
    found = sniff(list(targets), {u: SP.LABEL.get(x.get("_sport", "fb"), "Football") for u, x in targets.items()}) if targets else {}
    for url, t in targets.items():
        streams = [u for u in found.get(url, []) if "player_status" not in u and "/v5/" not in u and not NOT_LIVE.search(u) and not is_bad(t["school"], u, src)][:3]
        print(t["school"], t.get("_sport"), "->", streams)
        if streams:
            set_feeds(t, streams, STAMP, t.get("_sport", "fb")); changed = True
    for t in radio["teams"]:
        t.pop("_mins", None); t.pop("_sport", None)
    if SEEN_SHORT:
        print("other SIDEARM sport names seen:", ", ".join(sorted(SEEN_SHORT)))
    json.dump(radio, open("radio.json", "w"), indent=0)


if __name__ == "__main__":
    main()
