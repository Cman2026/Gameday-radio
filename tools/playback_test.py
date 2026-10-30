"""Play every stream the way a phone does: open the live site (https) in a real
browser and try each stream in an <audio> element, using hls.js for HLS like the
page does. Writes playback.json, which the page uses to order streams, swap in
secure (https) versions, and offer "open in Safari" for streams that only work
outside the page.

Usage: python tools/playback_test.py [today|tomorrow|live|all]
"""
import datetime, json, re, sys, time, urllib.parse, urllib.request
from playwright.sync_api import sync_playwright

SITE = "https://cman2026.github.io/Gameday-radio/"
UA = {"User-Agent": "Mozilla/5.0 (GamedayRadio playback test)"}
SB = "https://site.api.espn.com/apis/site/v2/sports/football/college-football/scoreboard?groups={g}&limit=400{d}"
ET = datetime.timezone(datetime.timedelta(hours=-4))


def norm(x):
    x = (x or "").lower().replace("&", " and ")
    x = re.sub(r"\bst\.?\b", "state", x)
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", x)).strip()


def teams_in_games(scope):
    if scope == "all":
        return None
    day = datetime.datetime.now(ET).date() + datetime.timedelta(days=1 if scope == "tomorrow" else 0)
    names = set()
    for g in (80, 81):
        try:
            url = SB.format(g=g, d=f"&dates={day:%Y%m%d}")
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=20) as r:
                for e in json.loads(r.read()).get("events", []):
                    if scope == "live" and e["status"]["type"]["state"] != "in":
                        continue
                    for c in e["competitions"][0]["competitors"]:
                        for k in ("location", "displayName", "shortDisplayName"):
                            names.add(norm(c["team"].get(k)))
        except Exception as ex:
            print("scoreboard error", ex)
    return names


def variants(u):
    """Secure versions to try for a plain-http stream."""
    if not u.startswith("http://"):
        return [u]
    p = urllib.parse.urlsplit(u)
    out = [urllib.parse.urlunsplit(("https", p.netloc, p.path, p.query, ""))]
    if p.port:
        out.append(urllib.parse.urlunsplit(("https", p.hostname, p.path, p.query, "")))
    return out + [u]


PLAY_JS = """async (url) => {
  const a = new Audio(); a.muted = true; let hls = null;
  const u = /securenetsystems\\.net\\//.test(url) && !/playSessionID=/.test(url)
    ? url + (url.includes('?') ? '&' : '?') + 'playSessionID=' + crypto.randomUUID().toUpperCase() : url;
  return await new Promise(res => {
    let finished = false;
    const done = (ok, why) => { if (finished) return; finished = true; clearTimeout(t);
      try { a.pause(); if (hls) hls.destroy(); a.removeAttribute('src'); a.load(); } catch (e) {} res({ok, why}); };
    const t = setTimeout(() => done(false, 'timeout'), 15000);
    a.addEventListener('playing', () => done(true, 'playing'));
    a.addEventListener('error', () => done(false, 'media error ' + (a.error && a.error.code)));
    if (/\\.m3u8(\\?|$)/i.test(u) && window.Hls && Hls.isSupported()) {
      hls = new Hls(); hls.on(Hls.Events.ERROR, (e, d) => { if (d.fatal) done(false, 'hls ' + d.details); });
      hls.loadSource(u); hls.attachMedia(a); a.play().catch(() => {});
    } else { a.src = u; a.play().catch(err => { if (!/interrupted|pause/i.test(String(err))) done(false, String(err).slice(0, 80)); }); }
  });
}"""


def main():
    scope = (sys.argv[1] if len(sys.argv) > 1 else "tomorrow").lower()
    want = teams_in_games(scope)
    radio = json.load(open("radio.json"))["teams"]
    teams = [t for t in radio if t.get("streams") and (want is None or any(norm(n) in want for n in [t["school"]] + (t.get("names") or [])))]
    print(f"testing {len(teams)} teams ({scope})")
    try:
        state = json.load(open("playback.json"))
    except Exception:
        state = {"streams": {}, "teams": {}}
    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    with sync_playwright() as p:
        try:
            b = p.chromium.launch(channel="chrome", args=["--autoplay-policy=no-user-gesture-required"])  # real Chrome: has AAC
        except Exception:
            b = p.chromium.launch(args=["--autoplay-policy=no-user-gesture-required"])
        pages = []
        for _ in range(6):
            pg = b.new_page(); pg.goto(SITE, wait_until="load", timeout=45000); pages.append(pg)
        jobs = [(t, u) for t in teams for s in t["streams"] for u in variants(s)]
        results = {}
        i = 0
        while i < len(jobs):
            batch = jobs[i:i + len(pages)]
            # start all tests in the batch at once, then collect
            for pg, (_, u) in zip(pages, batch):
                pg.evaluate(f"(url) => {{ window.__r = null; ({PLAY_JS})(url).then(r => window.__r = r); }}", u)
            deadline = time.time() + 20
            for pg, (t, u) in zip(pages, batch):
                r = None
                while r is None and time.time() < deadline:
                    r = pg.evaluate("window.__r")
                    if r is None: pg.wait_for_timeout(300)
                r = r or {"ok": False, "why": "no result"}
                results[u] = r
                state["streams"][u] = r | {"at": stamp, "school": t["school"]}
            i += len(pages)
        b.close()
    for t in teams:
        inpage = [u for s in t["streams"] for u in variants(s) if u.startswith("https") and results.get(u, {}).get("ok")]
        external = next((s for s in t["streams"] if s.startswith("http://")), None) if not inpage else None
        state["teams"][t["school"]] = {"inpage": list(dict.fromkeys(inpage)), "external": external, "at": stamp}
        print(f"{'OK ' if inpage else ('EXT' if external else 'BAD')} {t['school']}: {inpage[:1] or external or [results.get(s, {}).get('why') for s in t['streams']][:2]}")
    state["tested"] = stamp
    json.dump(state, open("playback.json", "w"), indent=1)


if __name__ == "__main__":
    main()
