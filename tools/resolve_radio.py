"""Find and test a free, playable stream for each team's flagship radio station.

Input:  tools/radio-sources.json -> [{school, names, conference, network, flagship,
         calls:["KXXX-AM"], station_website, streams:[...], listen_page}]
Output: radio.json (read by the page) and radio-report.json (what was tried).

Runs on GitHub Actions, which has open internet access. Streams found once are
remembered: a team keeps its last working stream until it fails three runs in a
row, or until its station changes.
"""
import html as htmlmod, json, re, threading, time, urllib.parse, urllib.request
from radio_common import is_bad, feeds_fresh, set_feeds, clean, load_sources
from concurrent.futures import ThreadPoolExecutor

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"}
AUDIO_CT = ("audio/", "application/ogg", "application/octet-stream", "video/mp2t")
HLS_CT = ("mpegurl", "application/vnd.apple")
DROP_AFTER = 3  # failed runs before a remembered stream is dropped


BOT_UA = {"User-Agent": "GamedayRadio/1.0 (https://cman2026.github.io/Gameday-radio/; stream finder)"}

def fetch(url, timeout=12, limit=600_000):
    req = urllib.request.Request(url, headers=BOT_UA if "wikipedia.org" in url else UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read(limit).decode("utf-8", "ignore"), r.geturl()


HOST_LIMIT = {"securenetsystems.net": threading.Semaphore(3)}  # hosts that throttle cloud servers

def probe(url, timeout=8):
    """(ok, detail): ok means the URL is answering with audio right now."""
    sem = next((v for k, v in HOST_LIMIT.items() if k in url), None)
    if sem:
        with sem:
            return _probe(url, timeout + 7)
    return _probe(url, timeout)


def _probe(url, timeout):
    try:
        req = urllib.request.Request(url, headers=UA | {"Icy-MetaData": "0"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            ct = (r.headers.get("content-type") or "").lower()
            r_len = r.headers.get("content-length")
            head = r.read(4096)
            final = r.geturl()
        if "restricted" in final or "unavailable" in final:
            return False, "placeholder audio"
        if any(h in ct for h in HLS_CT) or head.lstrip().startswith(b"#EXTM3U"):
            return ("#EXT" in head.decode("latin1", "ignore")), f"hls {final}"
        if r_len and int(r_len) < 50_000_000 and not ct.startswith("audio/aacp"):
            return False, f"fixed-length file ({r_len} bytes), not a live stream"
        if ct.startswith(AUDIO_CT) or head[:3] == b"ID3" or (len(head) > 1 and head[0] == 0xFF and head[1] & 0xE0 == 0xE0):
            return True, f"{ct} {final}"
        return False, f"not audio ({ct})"
    except Exception as e:
        return False, str(e)[:120]


# ---------- candidate sources, most trustworthy first ----------

STREAM_HOSTS = ("streamtheworld", "amperwave", "securenetsystems", "ihrhls", "streamguys", "cdnstream1",
                "streamon.fm", "radio.co", "zeno.fm", "mixlr", "liveradio", "lightningstream", "abacast",
                "centova", "rockhost", "yesstreaming", "exclusive.radio", "listen.", "stream.", "icecast", "shoutcast")
URL_RE = re.compile(r"""https?://[^\s"'<>()\\]+""")
STW_MOUNT_RE = re.compile(r"""(?:livestream-redirect/|tdstation=|station=|mount=|"mount"\s*:\s*")([A-Z0-9_]{4,24})""")


JUNK = re.compile(r"soundhelix|example|podtrac|omny\.fm|megaphone|libsyn|anchor\.fm|tunegenie|podcast|/episodes?/|/ads?/|silent\.mp3", re.I)

def looks_like_stream(u):
    lu = u.lower()
    if JUNK.search(u):
        return False
    if any(x in lu for x in (".png", ".jpg", ".svg", ".css", ".js", "facebook", "twitter", "instagram", "google", "apple.com", "/wp-content/")):
        return False
    return (lu.split("?")[0].endswith((".mp3", ".aac", ".m3u8", ".pls", ".m3u", "/stream", "/live", "/listen"))
            or any(h in lu for h in STREAM_HOSTS[:16]))


def from_page(url):
    """Stream URLs and StreamTheWorld mounts written in a station page."""
    try:
        text, final = fetch(url)
    except Exception:
        return [], []
    text = htmlmod.unescape(text).replace("\\/", "/")
    streams = [u.rstrip(".,;") for u in URL_RE.findall(text) if looks_like_stream(u)]
    streams += re.findall(r"""(?:data-stream|stream|streamUrl|"url")\s*[=:]\s*["'](https?://[^"']+)""", text)
    mounts = STW_MOUNT_RE.findall(text)
    links = [urllib.parse.urljoin(final, m) for m in re.findall(r"""href=["']([^"']*(?:listen|player|stream|live)[^"']*)["']""", text, re.I)]
    return streams, mounts + links


def station_site(team, call, band):
    sites = [team.get("station_website")] if team.get("station_website") else []
    if not sites:
        for title in ([f"{call}-{band}"] if band == "FM" else []) + [f"{call} ({band})" if band else call, call, f"{call}-FM", f"{call} (AM)"]:
            try:
                text, _ = fetch("https://en.wikipedia.org/api/rest_v1/page/html/" + urllib.parse.quote(title.replace(" ", "_")), limit=400_000)
            except Exception:
                continue
            m = re.search(r"Website</th>.*?href=\"(https?://[^\"]+)\"", text, re.S)
            if m:
                sites.append(m.group(1)); break
    out, mounts = [], []
    for site in sites:
        s, extra = from_page(site)
        out += s
        for x in extra[:6]:
            if x.startswith("http"):
                s2, m2 = from_page(x); out += s2; mounts += [m for m in m2 if not m.startswith("http")]
            else:
                mounts.append(x)
    out += [f"https://playerservices.streamtheworld.com/api/livestream-redirect/{m}{'' if m.endswith(('AAC','.mp3')) else 'AAC'}.aac" for m in dict.fromkeys(mounts) if call in m]
    return out


def directories(call, band):
    """Public station directories whose pages carry the raw stream URL."""
    c, b = call.lower(), band.lower()
    pages = [f"https://onlineradiobox.com/us/{c}/", f"https://onlineradiobox.com/us/{c}{b}/" if b else "",
             f"https://www.radio.net/s/{c}", f"https://www.radio.net/s/{c}{b}" if b else "",
             f"https://streema.com/radios/{call}", f"https://mytuner-radio.com/search/?q={call}"]
    out = []
    for pg in pages:
        if not pg: continue
        s_, _ = from_page(pg)
        out += [u for u in s_ if "onlineradiobox" not in u and "radio.net" not in u and "streema" not in u]
    return out


def iheart(call, band):
    out = []
    for cl in ([f"{call}-{band}"] if band else [f"{call}-AM", f"{call}-FM"]):
        try:
            text, _ = fetch("https://us.api.iheart.com/api/v2/content/liveStations?" + urllib.parse.urlencode({"callLetters": cl, "limit": 3}))
            for h in json.loads(text).get("hits", []):
                if (h.get("callLetters") or "").upper() != cl:
                    continue
                st = h.get("streams") or {}
                for k in ("secure_shoutcast_stream", "secure_hls_stream", "shoutcast_stream", "hls_stream"):
                    if st.get(k): out.append(st[k])
        except Exception:
            continue
    return out


def securenet(call):
    try:
        text, _ = fetch(f"https://radio.securenetsystems.net/v5/{call}")
        if call.upper() not in text.upper():
            return []
    except Exception:
        return []
    found = re.findall(r"https?://ice\d+\.securenetsystems\.net/[A-Za-z0-9_]+", text)
    return list(dict.fromkeys(found)) or [f"https://ice{n}.securenetsystems.net/{call}" for n in (1, 2, 3, 5, 6, 7, 8, 9, 10, 24, 25, 41, 64)]


def streamtheworld(call, band):
    bands = [band] if band else ["AM", "FM", ""]
    out = []
    for b in bands:
        for name in (f"{call}{b}AAC.aac", f"{call}{b}.mp3", f"{call}_{b}AAC.aac" if b else ""):
            if name: out.append(f"https://playerservices.streamtheworld.com/api/livestream-redirect/{name}")
    return out


def amperwave(call, band):
    """Audacy and Townsquare stations stream through Amperwave with predictable names."""
    c = call.lower(); out = []
    for b in ([band.lower()] if band else ["am", "fm"]):
        out.append(f"https://live.amperwave.net/manifest/audacy-{c}{b}aac-imc")
        for n in (1, 2, 3):  # Saga Communications stations
            out.append(f"https://live.amperwave.net/manifest/saga-{c}{b}aac-hlsc{n}.m3u8")
        out.append(f"https://live.amperwave.net/direct/audacy-{c}{b}aac-imc")
        for n in (1, 2, 3, 4):
            out.append(f"https://live.amperwave.net/manifest/townsquare-{c}{b}aac-ibc{n}")
    return out


def radio_browser(call, freq):
    """Community directory; only trusted when the frequency also matches."""
    out = []
    for host in ("de1", "nl1", "at1"):
        try:
            text, _ = fetch(f"https://{host}.api.radio-browser.info/json/stations/search?" + urllib.parse.urlencode({"name": call, "limit": 20, "hidebroken": "true"}))
            for st in json.loads(text):
                nm = (st.get("name", "") + " " + st.get("tags", "")).upper()
                if not re.search(rf"(?<![A-Z]){re.escape(call)}(?![A-Z])", nm):
                    continue
                if freq and freq not in nm.replace(" ", ""):
                    continue
                u = st.get("url_resolved") or st.get("url")
                if u: out.append(u)
            break
        except Exception:
            continue
    return out


def candidates(team):
    groups = [("given", list(team.get("streams") or []))]
    # The school's own listen page often embeds the stream (Mixlr, Stretch Internet, SIDEARM players).
    if team.get("listen_page"):
        found, extra = from_page(team["listen_page"])
        for x in extra[:6]:
            if x.startswith("http"): found += from_page(x)[0]
        groups.append(("listen-page", found))
    if team.get("securenet"):
        groups.append(("securenet-id", securenet(team["securenet"])))
    freqs = re.findall(r"\b(\d{2,4}(?:\.\d)?)\b", team.get("flagship") or "")
    for call in team.get("calls") or []:
        m = re.match(r"([KW][A-Z]{2,3})(?:-?(AM|FM))?$", call.upper().replace(" ", ""))
        if not m:
            continue
        base, band = m.group(1), m.group(2) or ""
        groups += [("iheart", iheart(base, band)), ("securenet", securenet(base)),
                   ("streamtheworld", streamtheworld(base, band)), ("website", station_site(team, base, band)),
                   ("directories", directories(base, band)), ("amperwave", amperwave(base, band)),
                   ("radio-browser", radio_browser(base, freqs[0] if freqs else ""))]
    seen = set(); out = []
    for src, urls in groups:
        for u in urls:
            if u and u not in seen:
                seen.add(u); out.append((src, u))
    return out


PREV = {}

def resolve(team):
    tried, good = [], []
    # Fast path: if the stream we found last time still plays and the station hasn't changed, keep it.
    old = PREV.get(team.get("school"), {})
    if old.get("streams") and old.get("calls") == team.get("calls"):
        for u in old["streams"]:
            if is_bad(team.get("school", ""), u, SOURCES):
                continue
            ok, detail = probe(u)
            tried.append({"url": u, "source": "remembered", "ok": ok, "detail": detail})
            if ok: good.append(u)
        if good:
            return good, tried
    sn_hit = False
    for src, u in candidates(team):
        if "securenetsystems.net" in u and sn_hit:
            continue
        ok, detail = probe(u)
        tried.append({"url": u, "source": src, "ok": ok, "detail": detail})
        if ok:
            good.append(u); sn_hit = sn_hit or "securenetsystems.net" in u
        if len(good) >= 3:
            break
    return good, tried


SOURCES = {}


def main():
    src = json.load(open("tools/radio-sources.json"))
    try:
        prev = {t["school"]: t for t in json.load(open("radio.json"))["teams"]}
    except Exception:
        prev = {}
    PREV.update(prev)
    SOURCES.update({x["school"]: x for x in src})
    with ThreadPoolExecutor(max_workers=32) as ex:
        results = list(ex.map(resolve, src))
    teams, report = [], []
    for t, (good, tried) in zip(src, results):
        old = prev.get(t.get("school"), {})
        base = lambda cs: sorted({re.sub(r"-?(AM|FM)$", "", c.upper()) for c in (cs or [])})
        same_station = "calls" not in old or base(old.get("calls")) == base(t.get("calls"))
        misses = 0
        remembered = [x for x in tried if x["source"] == "remembered"]
        # Timeouts and 403s usually mean the host is blocking cloud servers, not that the stream is gone.
        only_timeouts = bool(remembered) and all(re.search(r"timed out|timeout|403", x["detail"], re.I) for x in remembered)
        if not good and same_station and old.get("streams") and only_timeouts:
            good, misses = old["streams"], old.get("misses", 0)  # couldn't reach it from here; not proof it's dead
        elif not good and same_station and old.get("streams"):
            # Count at most one miss per day, so several runs in one day can't drop a stream.
            today = time.strftime("%Y-%m-%d")
            misses = old.get("misses", 0) + (0 if old.get("miss_day") == today else 1)
            if misses < DROP_AFTER:
                good = old["streams"]  # keep the last stream that worked
        if not good and t.get("game_only") and t.get("streams"):
            good = list(t["streams"])  # school game feeds are only on the air during games
        good = sorted(dict.fromkeys(good), key=lambda u: not u.startswith("https"))
        good = [u for u in good if not is_bad(t.get("school", ""), u, SOURCES)]
        entry = {k: t.get(k) for k in ("school", "names", "network", "flagship", "listen_page", "conference", "calls", "game_only", "no_radio", "notes")} \
                | {"streams": good, "misses": misses if good else 0,
                   "miss_day": time.strftime("%Y-%m-%d") if misses else None,
                   "last_ok": time.strftime("%Y-%m-%d") if misses == 0 and good else old.get("last_ok")}
        if feeds_fresh(old):  # today's game feeds stay in front of the station streams
            feeds = [u for u in old["game_feeds"] if not is_bad(t.get("school", ""), u, SOURCES)]
            set_feeds(entry, feeds, old["game_feeds_at"])
            entry["streams"] = list(dict.fromkeys(feeds + good))[:6]
        teams.append(entry)
        report.append({"school": t.get("school"), "calls": t.get("calls"), "ok": [x for x in tried if x["ok"]],
                       "kept_from_before": bool(misses), "failed": [x for x in tried if not x["ok"]][:15]})
    json.dump({"built": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "teams": teams}, open("radio.json", "w"), indent=0)
    json.dump(report, open("radio-report.json", "w"), indent=1)
    print(f"{sum(1 for x in teams if x['streams'])} of {len(teams)} teams have a working stream")


if __name__ == "__main__":
    main()
