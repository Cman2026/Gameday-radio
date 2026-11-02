"""One-off research helper: fetch pages listed in research-urls.txt ("label|kind|url" per line) and save
the parts that matter for finding broadcasts (title, sentences about radio/audio, and radio/listen links)
to research-pages.json. Runs in GitHub Actions, which can reach sites the research sandbox can't.
"""
import html, json, re, sys, urllib.request
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36",
      "Accept": "text/html,application/xhtml+xml,*/*"}
KEY = re.compile(r"\b(radio|audio|listen|broadcast|play.by.play|station|network|\d{2,3}\.\d ?(?:fm|the)|\d{3,4} ?am|sidearm|mixlr|varsity)\b", re.I)
LINK = re.compile(r"radio|audio|listen|showcase|stream|mixlr|tunein|iheart|\.mp3|\.m3u8|\.aac", re.I)


class Page(HTMLParser):
    def __init__(self):
        super().__init__(); self.text, self.links, self._a, self._skip, self.title, self._t = [], [], None, 0, "", False
    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in ("script", "style", "noscript"): self._skip += 1
        if tag == "title": self._t = True
        if tag == "a": self._a = [a.get("href") or "", a.get("aria-label") or a.get("title") or ""]
        if tag in ("audio", "source", "iframe") and a.get("src"): self.links.append((tag, a["src"]))
    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript"): self._skip = max(0, self._skip - 1)
        if tag == "title": self._t = False
        if tag == "a" and self._a is not None:
            self.links.append((self._a[1].strip(), self._a[0])); self._a = None
        if tag in ("p", "div", "li", "tr", "br", "h1", "h2", "h3", "h4", "td"): self.text.append("\n")
    def handle_data(self, d):
        if self._t: self.title += d
        if self._skip: return
        self.text.append(d)
        if self._a is not None: self._a[1] += " " + d


def get(line):
    label, kind, url = (line.split("|", 2) + ["", ""])[:3]
    out = {"label": label, "kind": kind, "url": url}
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=25) as r:
            raw = r.read(3_000_000).decode("utf-8", "ignore"); out["final"] = r.geturl(); out["status"] = r.status
    except Exception as ex:
        out["error"] = str(ex)[:120]; return out
    p = Page()
    try: p.feed(raw)
    except Exception: pass
    text = re.sub(r"[ \t\r\f\v]+", " ", html.unescape("".join(p.text)))
    lines = [l.strip() for l in re.split(r"\n+|(?<=[.!?])\s+", text) if l.strip()]
    out["title"] = p.title.strip()[:150]
    out["said"] = list(dict.fromkeys(l[:260] for l in lines if KEY.search(l) and len(l) > 12))[:15]
    out["links"] = list(dict.fromkeys(f"{t[:60]} -> {h[:200]}" for t, h in p.links if LINK.search(t + " " + h)))[:25]
    # Raw stream URLs written anywhere in the page source (players often embed them in scripts).
    out["streams"] = list(dict.fromkeys(re.findall(r"https?://[^\s\"'<>\\]+?\.(?:mp3|aac|m3u8)\b[^\s\"'<>\\]*|https?://[^\s\"'<>\\]*(?:streamtheworld|amperwave|securenetsystems|ihrhls|streamguys|surfernetwork|leanstream|mixlr)[^\s\"'<>\\]*", raw)))[:10]
    return out


def main():
    lines = [l.strip() for l in open(sys.argv[1] if len(sys.argv) > 1 else "research-urls.txt") if l.strip() and not l.startswith("#")]
    with ThreadPoolExecutor(max_workers=12) as ex:
        res = list(ex.map(get, lines))
    json.dump(res, open("research-pages.json", "w"), indent=1)
    print(sum(1 for r in res if "error" not in r), "of", len(res), "pages fetched")


if __name__ == "__main__":
    main()
