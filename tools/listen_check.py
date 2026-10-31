"""Actually listen to each live game's streams: record ~15 seconds, transcribe it with a small
speech-to-text model, and look for football play-by-play words. This catches stations that are
playing music or other shows instead of the game, which the "now playing" titles usually can't.

Writes a "heard" verdict into radio-heard.json for each stream:
  game      - play-by-play heard (downs, yards, team names, ...)
  not_game  - clear speech or lyrics with nothing about football, twice in a row
  quiet     - nothing intelligible (music without vocals, silence, or an ad bed)
"""
import json, os, re, subprocess, sys, tempfile, time, urllib.request, uuid
from concurrent.futures import ThreadPoolExecutor

UA = {"User-Agent": "Mozilla/5.0 (GamedayRadio listen check)"}
SB = "https://site.api.espn.com/apis/site/v2/sports/football/college-football/scoreboard?groups={}&limit=400"
FOOTBALL = re.compile(r"\b(yard|yards|yard line|first down|second down|third down|fourth down|down and|touchdown|field goal|"
                      r"kickoff|punt|quarterback|snap|handoff|tackle[ds]?|sack(ed)?|interception|fumble|incomplete|complete[ds]?|"
                      r"end zone|red zone|line of scrimmage|timeout|offense|defense|drive|huddle|shotgun|pass(ed|es)?|rush(ed|es)?|"
                      r"penalty|holding|scrimmage|quarter|halftime|football|first and ten|and goal|at the \d+|the \d+ yard|"
                      r"offsides|false start|pass interference|touchback|fair catch|two.point|onside|hail mary|play.action|"
                      r"stadium|scoreboard|the kick|leads? \d+|trails? \d+|\d{1,2} ?(?:to|-) ?\d{1,2})\b", re.I)


def norm(x):
    x = (x or "").lower().replace("&", " and ")
    x = re.sub(r"\bst\.?\b", "state", x)
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", x)).strip()


def live_games():
    out = []
    for g in (80, 81):
        try:
            with urllib.request.urlopen(urllib.request.Request(SB.format(g), headers=UA), timeout=20) as r:
                out += [e for e in json.loads(r.read()).get("events", []) if e["status"]["type"]["state"] == "in"]
        except Exception as ex:
            print("scoreboard error", ex)
    return out


def record(url, secs=15):
    if "securenetsystems.net/" in url and "playSessionID" not in url:
        url += ("&" if "?" in url else "?") + "playSessionID=" + str(uuid.uuid4()).upper()
    f = tempfile.mktemp(suffix=".wav")
    try:
        subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-rw_timeout", "15000000", "-user_agent", UA["User-Agent"],
                        "-i", url, "-t", str(secs), "-ac", "1", "-ar", "16000", "-y", f], timeout=secs + 30, check=True)
        return f if os.path.getsize(f) > 32000 else None
    except Exception:
        return None


def main():
    from faster_whisper import WhisperModel
    model = WhisperModel("tiny.en", device="cpu", compute_type="int8")
    games = live_games()
    if not games:
        print("no live games"); return
    radio = json.load(open("radio.json"))["teams"]
    index = {}
    for t in radio:
        for n in [t.get("school")] + (t.get("names") or []):
            if n: index.setdefault(norm(n), t)
    jobs = []
    for e in games:
        for c in e["competitions"][0]["competitors"]:
            tm = c["team"]
            t = next((index[norm(n)] for n in (tm.get("location"), tm.get("displayName"), tm.get("shortDisplayName")) if norm(n) in index), None)
            if not t:
                continue
            # mascot and abbreviation only: place words like "state" or "carolina" show up in news too
            words = {w for w in norm(" ".join([tm.get("name") or "", tm.get("abbreviation") or ""])).split() if len(w) > 2} - {"state", "university", "college"}
            for u in [u for u in (t.get("streams") or []) if u.startswith("http")][:3]:
                jobs.append((t["school"], u, words))
    print(f"listening to {len(jobs)} streams in {len(games)} live games")
    def transcribe(clip):
        import wave, numpy as np
        with wave.open(clip) as w:
            pcm = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0
        segs, _ = model.transcribe(pcm, beam_size=1, vad_filter=True)
        os.remove(clip)
        return " ".join(sg.text for sg in segs).strip()

    def judge(text, words):
        """game / blocked / speech (talk or lyrics with no football in it) / quiet"""
        if re.search(r"right access to future sporting events|geofence|not available in your (area|market)|outside of the (broadcast )?area", text, re.I):
            return "blocked"
        terms = {m.group(0).lower() for m in FOOTBALL.finditer(text)}
        hits = len(terms) + sum(2 for w in words if re.search(rf"\b{re.escape(w)}\b", text, re.I))
        if hits >= 2:
            return "game"
        return "speech" if len(text.split()) >= 12 else "quiet"

    def listen(job):
        clip = record(job[1])
        return (None, None) if not clip else (lambda t: (t, judge(t, job[2])))(transcribe(clip))

    with ThreadPoolExecutor(max_workers=8) as ex:
        first = list(ex.map(listen, jobs))
    # Anything that sounded like plain talk may just have been a commercial break: listen again
    # about a minute later before counting it against the station.
    again = [i for i, (t, v) in enumerate(first) if v == "speech"]
    if again:
        time.sleep(50)
        with ThreadPoolExecutor(max_workers=8) as ex:
            second = dict(zip(again, ex.map(lambda i: listen(jobs[i]), again)))
    else:
        second = {}
    try:
        state = json.load(open("radio-heard.json"))
    except Exception:
        state = {"streams": {}}
    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    summary = {}
    for i, ((school, url, words), (text, v)) in enumerate(zip(jobs, first)):
        rec = state["streams"].setdefault(url, {"school": school})
        if v is None:
            rec.update({"heard": "no_audio", "heard_at": stamp}); summary.setdefault("no_audio", []).append(school); continue
        if i in second and second[i][1] is not None:
            t2, v2 = second[i]
            if v2 != "speech":
                text, v = t2, v2   # the second listen settled it
            else:
                text = f"{text} || {t2}"
        if v == "speech":
            v = "not_game" if rec.get("heard_raw") == "not_game" else "maybe_not"  # two runs in a row with no football
            rec["heard_raw"] = "not_game"
        else:
            rec["heard_raw"] = v
        rec.update({"heard": v if v in ("not_game", "blocked", "game", "quiet") else "unknown",
                    "heard_text": text[:200], "heard_at": stamp})
        summary.setdefault(v, []).append(school)
        print(f"{v:10} {school[:34]:34} {text[:90]!r}")
    state["listened"] = stamp
    json.dump(state, open("radio-heard.json", "w"), indent=1)
    print({k: len(v) for k, v in summary.items()})


if __name__ == "__main__":
    main()
