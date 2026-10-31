"""Second look at teams marked "no radio": open each school's football schedule page
(and its next game page) in a real browser and record every radio/audio mention and
audio-looking link. Writes audio-check.json.

Usage: python tools/check_audio.py            # all teams marked no_radio
       python tools/check_audio.py "Penn" ...  # named schools only
"""
import json, re, sys
from playwright.sync_api import sync_playwright

AUDIO = re.compile(r"radio|audio|listen|leanplayer|mixlr|tunein|streamtheworld|securenet|varsity ?network|"
                   r"iheart|audacy|am\b|fm\b|\b\d{2,3}\.\d ?fm|\b\d{3,4} ?am\b|type=live|live=", re.I)
LINK = re.compile(r"leanplayer|mixlr|tunein|streamtheworld|securenetsystems|thevarsitynetwork|iheart|audacy|radio|audio|"
                  r"listen|type=Live|showcase|\.mp3|\.m3u8|\.aac|stretchinternet|lightningstream|sportsjuice", re.I)


def snippets(text):
    out = []
    for m in re.finditer(r"[^\n.]{0,80}\b(radio|audio|listen)\b[^\n.]{0,80}", text, re.I):
        s = re.sub(r"\s+", " ", m.group(0)).strip()
        if s not in out:
            out.append(s)
    return out[:25]


def main():
    src = json.load(open("tools/radio-sources.json"))
    want = sys.argv[1:]
    teams = [s for s in src if (any(w.lower() in s["school"].lower() for w in want) if want else s.get("no_radio")) and s.get("athletics_site")]
    res = {}
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36")
        for s in teams:
            site = s["athletics_site"].rstrip("/")
            r = {"pages": {}}
            pg = ctx.new_page()
            for url in [f"{site}/sports/football/schedule", f"{site}/sports/football/schedule/2026"]:
                try:
                    pg.goto(url, wait_until="domcontentloaded", timeout=30000); pg.wait_for_timeout(2500)
                    text = pg.inner_text("body")
                    links = pg.eval_on_selector_all("a[href]", "els => els.map(e => [e.innerText.trim().slice(0,60), e.href])")
                    alinks = sorted({f"{t} -> {h}" for t, h in links if LINK.search(h) or re.search(r"radio|audio|listen", t, re.I)})[:40]
                    games = [h for t, h in links if re.search(r"/sports/football/schedule/\d{4}/.+|boxscore|game-notes|notes", h)]
                    r["pages"][url] = {"snippets": snippets(text), "links": alinks}
                    if games and "game" not in r:
                        r["game"] = games[0]
                    break
                except Exception as e:
                    r["pages"][url] = {"error": str(e)[:120]}
            # look at one game page too, where SIDEARM lists TV / radio per game
            if r.get("game"):
                try:
                    pg.goto(r["game"], wait_until="domcontentloaded", timeout=30000); pg.wait_for_timeout(2000)
                    text = pg.inner_text("body")
                    links = pg.eval_on_selector_all("a[href]", "els => els.map(e => [e.innerText.trim().slice(0,60), e.href])")
                    r["pages"][r["game"]] = {"snippets": snippets(text),
                                            "links": sorted({f"{t} -> {h}" for t, h in links if LINK.search(h) or re.search(r"radio|audio|listen", t, re.I)})[:40]}
                except Exception as e:
                    r["pages"][r["game"]] = {"error": str(e)[:120]}
            pg.close()
            res[s["school"]] = r
            print(s["school"], "->", sum(len(v.get("snippets", [])) + len(v.get("links", [])) for v in r["pages"].values()), "hits")
        b.close()
    json.dump(res, open("audio-check.json", "w"), indent=1)


if __name__ == "__main__":
    main()
