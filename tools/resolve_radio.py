"""Resolve each team's flagship radio station to a working, free audio stream.

Input:  tools/radio-sources.json  -> [{names, network, flagship, calls:[...], streams:[...], listen_page}]
Output: radio.json (served to the page) and radio-report.json (what was tried).
Runs on GitHub Actions, which has open internet access."""
import json, re, time, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor

UA = {"User-Agent": "Mozilla/5.0 (GamedayRadio stream checker)", "Icy-MetaData": "0"}
AUDIO_CT = ("audio/", "application/ogg", "application/octet-stream", "video/mp2t")
HLS_CT = ("mpegurl", "application/vnd.apple")

def probe(url, timeout=7):
    """Return (ok, detail). ok means the URL answers with audio right now."""
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            ct = (r.headers.get("content-type") or "").lower()
            head = r.read(4096)
            final = r.geturl()
        if any(h in ct for h in HLS_CT) or head.lstrip().startswith(b"#EXTM3U"):
            return ("#EXT-X" in head.decode("latin1", "ignore")), f"hls {ct} {final}"
        if ct.startswith(AUDIO_CT) or head[:3] == b"ID3" or (len(head) > 1 and head[0] == 0xFF and head[1] & 0xE0 == 0xE0):
            if "restricted" in final:
                return False, "restricted placeholder"
            return True, f"{ct} {final}"
        return False, f"not audio: {ct}"
    except Exception as e:
        return False, str(e)[:120]

def radio_browser(call):
    out = []
    for host in ("de1", "nl1", "at1"):
        try:
            url = f"https://{host}.api.radio-browser.info/json/stations/search?" + urllib.parse.urlencode({"name": call, "limit": 15, "hidebroken": "true"})
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=12) as r:
                for st in json.loads(r.read()):
                    nm = (st.get("name", "") + " " + st.get("tags", "")).upper()
                    if re.search(rf"\b{re.escape(call)}\b", nm):
                        u = st.get("url_resolved") or st.get("url")
                        if u: out.append(u)
            break
        except Exception:
            continue
    return out

def securenet(call):
    # The station player page exists only for SecureNet customers; then find the live ice server.
    try:
        with urllib.request.urlopen(urllib.request.Request(f"https://radio.securenetsystems.net/v5/{call}", headers=UA), timeout=10) as r:
            html = r.read().decode("utf-8", "ignore")
        if call.upper() not in html.upper():
            return []
    except Exception:
        return []
    found = re.findall(r"https?://ice\d+\.securenetsystems\.net/[A-Za-z0-9_]+", html)
    if found:
        return list(dict.fromkeys(found))
    return [f"https://ice{n}.securenetsystems.net/{call}" for n in range(1, 48)]

def streamtheworld(call, band):
    names = []
    for b in ([band] if band else []) + ["AM", "FM", ""]:
        for fmt in (f"{call}{b}AAC.aac", f"{call}{b}.mp3", f"{call}_{b}.mp3" if b else None):
            if fmt and fmt not in names: names.append(fmt)
    return [f"https://playerservices.streamtheworld.com/api/livestream-redirect/{n}" for n in names]

def candidates(team):
    c = list(team.get("streams", []))
    for call in team.get("calls", []):
        m = re.match(r"([KW][A-Z]{2,3})(?:-?(AM|FM))?$", call.upper())
        if not m: continue
        base, band = m.group(1), m.group(2) or ""
        c += radio_browser(base)
        c += securenet(base)
        c += streamtheworld(base, band)
    seen = set(); return [u for u in c if not (u in seen or seen.add(u))]

def resolve(team):
    tried, good = [], []
    cands = candidates(team)
    # SecureNet brute-force lists are long; stop at the first live server.
    sn_hit = False
    for u in cands:
        if "securenetsystems.net" in u and sn_hit: continue
        ok, detail = probe(u)
        tried.append({"url": u, "ok": ok, "detail": detail})
        if ok:
            good.append(u)
            if "securenetsystems.net" in u: sn_hit = True
        if len(good) >= 3: break
    return good, tried

src = json.load(open("tools/radio-sources.json"))
with ThreadPoolExecutor(max_workers=16) as ex:
    results = list(ex.map(resolve, src))
teams, report = [], []
for t, (good, tried) in zip(src, results):
    # prefer https for an https page; keep http as a last resort
    good.sort(key=lambda u: (not u.startswith("https"),))
    teams.append({k: t.get(k) for k in ("school", "names", "network", "flagship", "listen_page", "conference")} | {"streams": good})
    report.append({"school": t.get("school"), "calls": t.get("calls"), "ok": good, "tried": [x for x in tried if not x["ok"]][:12]})
json.dump({"built": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "teams": teams}, open("radio.json", "w"), indent=0)
json.dump(report, open("radio-report.json", "w"), indent=1)
print(f"{sum(1 for t in teams if t['streams'])} of {len(teams)} teams have a working stream")
