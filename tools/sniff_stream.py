"""Open station/listen pages in a real browser, press play, and record the audio
stream URLs the page's player loads. Usage: python tools/sniff_stream.py URL [URL...]"""
import json, re, sys, time, urllib.parse, urllib.request
from playwright.sync_api import sync_playwright

STREAMY = re.compile(r"\.(mp3|aac|m3u8|pls|m3u)(\?|$)|streamtheworld|amperwave|securenetsystems|ihrhls|streamguys|cdnstream1|"
                     r"streamon\.fm|radio\.co|zeno\.fm|mixlr|icecast|shoutcast|/stream|/live|lightningstream|liveradio|stretchinternet", re.I)
def wiki_site(call):
    """call:KGO-AM -> the station website from its Wikipedia infobox."""
    base, _, band = call.partition("-")
    for title in ([f"{base}-FM"] if band == "FM" else []) + [f"{base} ({band})" if band else base, base, f"{base} (AM)", f"{base}-FM"]:
        try:
            req = urllib.request.Request("https://en.wikipedia.org/api/rest_v1/page/html/" + urllib.parse.quote(title.replace(" ", "_")),
                                         headers={"User-Agent": "GamedayRadio/1.0 (https://cman2026.github.io/Gameday-radio/)"})
            html = urllib.request.urlopen(req, timeout=12).read().decode("utf-8", "ignore")
            m = re.search(r"Website</th>.*?href=\"(https?://[^\"]+)\"", html, re.S)
            if m: return m.group(1)
        except Exception:
            continue
    return None

targets = []
for a in sys.argv[1:]:
    if a.startswith("call:"):
        site = wiki_site(a[5:])
        if site: targets.append(site)
        else: print("no website for", a)
    else:
        targets.append(a)
results = {}
with sync_playwright() as p:
    b = p.chromium.launch(args=["--autoplay-policy=no-user-gesture-required"])
    for url in dict.fromkeys(targets):
        found, media, bodies = [], [], {}
        ctx = b.new_context(ignore_https_errors=True, user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36")
        page = ctx.new_page()
        def on_req(r):
            if r.resource_type == "media" or (STREAMY.search(r.url) and not re.search(r"\.(js|css|png|jpg|svg|woff2?)(\?|$)", r.url)):
                found.append(r.url)
        ctx.on("request", on_req)
        def on_resp(r):
            try:
                ct = r.headers.get("content-type", "")
                if ("json" in ct or "station" in r.url) and len(bodies) < 8:
                    t = r.text()
                    if re.search(r"stream|mount|\.aac|\.mp3|m3u8", t, re.I) and len(t) < 60000:
                        bodies[r.url] = t[:6000]
            except Exception:
                pass
        ctx.on("response", on_resp)
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(4000)
            for sel in ["text=/listen live/i", "text=/listen now/i", "text=/^listen$/i", "[aria-label*='play' i]", "button:has-text('Play')", ".play", "#play", "[class*='play' i]", "button[title*='play' i]", "[data-testid*='play' i]", "svg[class*='play' i]", "#playButton", ".play-button", "button >> nth=0"]:
                for frame in page.frames:
                    try:
                        el = frame.locator(sel).first
                        if el.count() and el.is_visible():
                            el.click(timeout=3000); page.wait_for_timeout(4000)
                    except Exception:
                        pass
            for pg in ctx.pages:
                for frame in pg.frames:
                    try:
                        media += frame.evaluate("Array.from(document.querySelectorAll('audio,video,source')).map(e=>e.currentSrc||e.src).filter(Boolean)")
                    except Exception:
                        pass
        except Exception as e:
            found.append(f"error: {e}")
        results[url] = {"requests": list(dict.fromkeys(found))[:40], "media_elements": list(dict.fromkeys(media)),
                        "pages_opened": [x.url for x in ctx.pages], "json_bodies": bodies}
        ctx.close()
    b.close()
json.dump(results, open("sniff-result.json", "w"), indent=1)
print(json.dumps(results, indent=1)[:4000])
