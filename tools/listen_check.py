"""Actually listen to each live game's streams: record ~15 seconds, transcribe it with a small
speech-to-text model, and look for play-by-play words for that sport (football, basketball,
hockey, volleyball, baseball, softball). This catches stations that are
playing music or other shows instead of the game, which the "now playing" titles usually can't.

Writes a "heard" verdict into radio-heard.json for each stream:
  game      - play-by-play heard (downs, yards, team names, ...)
  not_game  - clear speech or lyrics with nothing about football, twice in a row
  quiet     - nothing intelligible (music without vocals, silence, or an ad bed)
"""
import json, os, re, subprocess, sys, tempfile, time, urllib.request, uuid
from concurrent.futures import ThreadPoolExecutor
import sports as SP

UA = {"User-Agent": "Mozilla/5.0 (GamedayRadio listen check)"}
FOOTBALL = re.compile(r"\b(yard|yards|yard line|first down|second down|third down|fourth down|down and|touchdown|field goal|"
                      r"kickoff|punt|quarterback|snap|handoff|tackle[ds]?|sack(ed)?|interception|fumble|incomplete|complete[ds]?|"
                      r"end zone|red zone|line of scrimmage|timeout|offense|defense|drive|huddle|shotgun|pass(ed|es)?|rush(ed|es)?|"
                      r"penalty|holding|scrimmage|quarter|halftime|football|first and ten|and goal|at the \d+|the \d+ yard|"
                      r"offsides|false start|pass interference|touchback|fair catch|two.point|onside|hail mary|play.action|"
                      r"stadium|scoreboard|the kick|leads? \d+|trails? \d+|\d{1,2} ?(?:to|-) ?\d{1,2}|"
                      r"yard line|goal line|boundary|sideline|receiver|running back|linebacker|cornerback|safety|safeties|"
                      r"goes down|brought down|out of bounds|inside the \d+|the \d+|\d+ yard|carries|carry|catch|caught|"
                      r"throws?|threw|runs? (?:it|left|right|up)|hand ?off|first and|second and|third and|fourth and)\b", re.I)
_COMMON = r"timeout|time out|leads? \d+|trails? \d+|\d{1,3} ?(?:to|-) ?\d{1,3}|score[sd]?|tied|halftime|play.by.play|the crowd|"
BASKETBALL = re.compile(r"\b(" + _COMMON + r"basketball|three|3.pointer|three.pointer|jumper|jump shot|layup|lay.in|dunk|slam|rebound|"
                        r"free throws?|foul(ed|s)?|and one|assist|steal|turnover|block(ed)?|shot clock|possession|paint|baseline|"
                        r"top of the key|corner|wing|elbow|bucket|hoop|rim|backboard|glass|fast break|in transition|inbound|"
                        r"half court|full court|press|zone|man.to.man|bonus|double bonus|tip.off|second half|first half|"
                        r"quarter|overtime|guard|forward|center|point guard|pick and roll|screen|drive[sd]?|pull.up|floater)\b", re.I)
HOCKEY = re.compile(r"\b(" + _COMMON + r"hockey|puck|goal(ie|tender)?|save[ds]?|shot on goal|power play|penalty kill|short.handed|"
                    r"penalty|minor|major|period|faceoff|face.off|blue line|red line|crease|slot|the net|between the pipes|"
                    r"glove|blocker|pad save|rebound|wrist shot|slap shot|one.timer|icing|offside|zamboni|ice|skate[sd]?|"
                    r"boards|forecheck|breakaway|odd.man rush|empty net|wing|defenseman|center ice|neutral zone|"
                    r"zone|clear(ed|s)?|dump(ed|s)? it in)\b", re.I)
VOLLEYBALL = re.compile(r"\b(" + _COMMON + r"volleyball|kill|ace|serve[sd]?|serving|service error|dig|block(ed|s)?|set point|"
                        r"match point|side.?out|rally|attack(er|ing)?|hitter|outside hitter|middle|setter|libero|"
                        r"the net|net violation|out of bounds|in the antenna|first set|second set|third set|fourth set|"
                        r"fifth set|the set|sets|swing|tip|roll shot|pass(ed)?|overpass|joust|rotation|challenge|point)\b", re.I)
BASEBALL = re.compile(r"\b(" + _COMMON + r"baseball|softball|pitch(es|er|ed)?|strike(s|out)?|struck out|ball (one|two|three|four)|"
                      r"one ball|two balls|three balls|full count|the count|inning|top of the|bottom of the|outs?|"
                      r"runners?|on (first|second|third)|first base|second base|third base|home plate|base hit|single|"
                      r"double|triple|home run|homer|grand slam|fly ball|fly out|pop(ped)? up|ground(ed)? (ball|out|into)|"
                      r"line drive|double play|bunt|stolen base|steal|walk(ed)?|hit by (a |the )?pitch|batter|at bat|"
                      r"dugout|bullpen|mound|catcher|shortstop|infield|outfield|left field|center field|right field|"
                      r"foul ball|fouled|swing(ing)?|swung|called strike|rbi|left on base|extra innings)\b", re.I)
VOCAB = {"fb": FOOTBALL, "mbb": BASKETBALL, "wbb": BASKETBALL, "mhk": HOCKEY, "whk": HOCKEY,
         "wvb": VOLLEYBALL, "bsb": BASEBALL, "sb": BASEBALL}
MAX_STREAMS = 140  # what fits in one run: football first, then the other sports, least recently heard first


def norm(x):
    x = (x or "").lower().replace("&", " and ")
    x = re.sub(r"\bst\.?\b", "state", x)
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", x)).strip()


def record(url, secs=15, skip=None):
    # Many official school feeds play an ad to every new listener; listen past it.
    if skip is None:
        skip = 35 if re.search(r"leanstream|jwplayer|revma|ihrhls|amperwave", url) else 8
    if "securenetsystems.net/" in url and "playSessionID" not in url:
        url += ("&" if "?" in url else "?") + "playSessionID=" + str(uuid.uuid4()).upper()
    f = tempfile.mktemp(suffix=".wav")
    try:
        subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-rw_timeout", "15000000", "-user_agent", UA["User-Agent"],
                        "-i", url, "-ss", str(skip), "-t", str(secs), "-ac", "1", "-ar", "16000", "-y", f], timeout=secs + skip + 40, check=True)
        return f if os.path.getsize(f) > 32000 else None
    except Exception:
        return None


def main():
    from faster_whisper import WhisperModel
    model = WhisperModel("tiny.en", device="cpu", compute_type="int8")
    games = SP.live()
    if not games:
        print("no live games"); return
    radio = json.load(open("radio.json"))["teams"]
    index = SP.directory_index(radio)
    try:
        state = json.load(open("radio-heard.json"))
    except Exception:
        state = {"streams": {}}
    # mascot and abbreviation only: place words like "state" or "carolina" show up in news too
    GENERIC = {"state", "university", "college", "north", "south", "east", "west", "central", "carolina", "texas", "florida",
               "georgia", "virginia", "new", "san", "the", "of", "southern", "northern", "eastern", "western", "miami", "saint"}
    jobs, seen = [], set()
    for sid, e in games:
        for c in e["competitions"][0]["competitors"]:
            tm = c["team"]
            t = SP.find_team(index, tm)
            if not t:
                continue
            words = {w for w in norm(" ".join([tm.get("location") or "", tm.get("name") or "", tm.get("abbreviation") or ""])).split() if len(w) > 2} - GENERIC
            for u in [u for u in SP.streams_for(t, sid) if u.startswith("http")][:3]:
                if (sid, u) in seen: continue
                seen.add((sid, u))
                jobs.append((t["school"], u, words, sid))
    order = list(SP.SPORTS)
    last = lambda j: (state["streams"].get(SP.key(j[3], j[1])) or {}).get("heard_at", "")
    jobs.sort(key=lambda j: (j[3] != "fb", last(j), order.index(j[3])))
    skipped = max(0, len(jobs) - MAX_STREAMS)
    jobs = jobs[:MAX_STREAMS]
    if skipped:
        print(f"{skipped} more streams wait for the next run")
    print(f"listening to {len(jobs)} streams in {len(games)} live games")
    def transcribe(clip):
        import wave, numpy as np
        with wave.open(clip) as w:
            pcm = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0
        segs, _ = model.transcribe(pcm, beam_size=1, vad_filter=True)
        os.remove(clip)
        return " ".join(sg.text for sg in segs).strip()

    def judge(text, words, sid):
        """game / blocked / speech (talk or lyrics with no football in it) / quiet"""
        if re.search(r"right access to future sporting events|geofence|not available in your (area|market)|outside of the (broadcast )?area", text, re.I):
            return "blocked"
        terms = {m.group(0).lower() for m in VOCAB[sid].finditer(text)}
        hits = len(terms) + sum(2 for w in words if re.search(rf"\b{re.escape(w)}\b", text, re.I))
        if hits >= 2:
            return "game"
        return "speech" if len(text.split()) >= 12 else "quiet"

    def listen(job):
        clip = record(job[1])
        return (None, None) if not clip else (lambda t: (t, judge(t, job[2], job[3])))(transcribe(clip))

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
    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    summary = {}
    for i, ((school, url, words, sid), (text, v)) in enumerate(zip(jobs, first)):
        rec = state["streams"].setdefault(SP.key(sid, url), {"school": school})
        rec["sport"] = sid
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
        print(f"{v:10} {sid:4} {school[:30]:30} {text[:90]!r}")
    state["listened"] = stamp
    cut = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 2 * 86400))
    state["streams"] = {k: v for k, v in state["streams"].items() if v.get("heard_at", "") >= cut}
    json.dump(state, open("radio-heard.json", "w"), indent=1)
    print({k: len(v) for k, v in summary.items()})


if __name__ == "__main__":
    main()
