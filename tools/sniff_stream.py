"""Open station/listen pages in a real browser, press play, and record the audio
stream URLs the page's player loads. Usage: python tools/sniff_stream.py URL [URL...]"""
import json, re, sys, time
from playwright.sync_api import sync_playwright

STREAMY = re.compile(r"\.(mp3|aac|m3u8|pls|m3u)(\?|$)|streamtheworld|amperwave|securenetsystems|ihrhls|streamguys|cdnstream1|"
                     r"streamon\.fm|radio\.co|zeno\.fm|mixlr|icecast|shoutcast|/stream|/live|lightningstream|liveradio|stretchinternet", re.I)
results = {}
with sync_playwright() as p:
    b = p.chromium.launch(args=["--autoplay-policy=no-user-gesture-required"])
    for url in sys.argv[1:]:
        found, media = [], []
        ctx = b.new_context(user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36")
        page = ctx.new_page()
        def on_req(r):
            if r.resource_type == "media" or (STREAMY.search(r.url) and not re.search(r"\.(js|css|png|jpg|svg|woff2?)(\?|$)", r.url)):
                found.append(r.url)
        ctx.on("request", on_req)
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(4000)
            for sel in ["text=/listen live/i", "text=/listen now/i", "text=/^listen$/i", "[aria-label*='play' i]", "button:has-text('Play')", ".play", "#play", "[class*='play' i]"]:
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
                        "pages_opened": [x.url for x in ctx.pages]}
        ctx.close()
    b.close()
json.dump(results, open("sniff-result.json", "w"), indent=1)
print(json.dumps(results, indent=1)[:4000])
