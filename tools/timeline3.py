import json, sys, time
from datetime import datetime, timezone, timedelta
import requests
from xml.etree import ElementTree as ET

D = "C:/visual projects/parser/data/"
S = requests.Session()
S.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"})

ANCHORS = {
    "Claude Opus 5.5": [("xor_journal","2026-09-22T16:31"),("neuraldvig","2026-09-22T16:32"),
                        ("hiaimedia","2026-09-22T18:06"),("seeallochnaya","2026-09-22T18:08"),
                        ("denissexy","2026-09-22T22:08")],
    "GPT-6.1 Sol":     [("xor_journal","2026-09-29T17:11"),("whackdoor","2026-09-29T17:14"),
                        ("seeallochnaya","2026-09-29T17:18"),("naebnet","2026-09-29T17:21")],
    "Dots agents":     [("whackdoor","2026-09-29T17:10"),("naebnet","2026-09-29T17:10"),
                        ("xor_journal","2026-09-29T17:11"),("technomedia","2026-09-29T17:14")],
    "Starship orbit":  [("hiaimedia","2026-09-28T15:07"),("rozetked","2026-09-28T18:43")],
    "Codex burned $80k":[("neuraldvig","2026-09-27T21:36"),("xor_journal","2026-09-28T05:38")],
    "OpenAI agent escape":[("data_secrets","2026-09-26T12:39"),("denissexy","2026-09-26T16:39")],
    "Meta VR glasses": [("naebnet","2026-09-24T10:14"),("cgevent","2026-09-25T13:54")],
    "Claude Sonnet 5.5":[("data_secrets","2026-09-25T18:06"),("ai_ml","2026-09-28T18:05"),
                        ("xor_journal","2026-09-28T18:15")],
    "Trump super intelligence":[("data_secrets","2026-09-22T16:31"),("rozetked","2026-09-23T07:30"),
                        ("hiaimedia","2026-09-23T08:25")],
    "DrivingBench":    [("hiaimedia","2026-09-25T06:21")],
    "Diden spider robot":[("neuraldvig","2026-09-28T10:47")],
    "ChatGPT $500 tier":[("ai_newz","2026-09-29T08:10"),("xor_journal","2026-09-29T17:22")],
}
Q = {
    "Claude Opus 5.5": "Claude Opus 5.5",
    "GPT-6.1 Sol": "GPT 6.1 Sol",
    "Dots agents": "OpenAI Dots",
    "Starship orbit": "Starship orbit",
    "Codex burned $80k": "Codex agent tokens bill",
    "OpenAI agent escape": "OpenAI agent sandbox",
    "Meta VR glasses": "Meta VR glasses",
    "Claude Sonnet 5.5": "Claude Sonnet 5.5",
    "Trump super intelligence": "Trump super intelligence AI",
    "DrivingBench": "DrivingBench",
    "Diden spider robot": "Diden Robotics",
    "ChatGPT $500 tier": "ChatGPT Pro Max subscription",
}
WINDOW = (datetime(2026, 9, 15, tzinfo=timezone.utc),
          datetime(2026, 10, 2, tzinfo=timezone.utc))


def hn(q):
    try:
        r = S.get("https://hn.algolia.com/api/v1/search_by_date",
                  params={"query": q, "tags": "story", "hitsPerPage": 60}, timeout=25)
        out = []
        for h in r.json().get("hits", []):
            if not h.get("created_at_i"):
                continue
            t = datetime.fromtimestamp(h["created_at_i"], timezone.utc)
            if WINDOW[0] <= t <= WINDOW[1]:
                out.append((t, h.get("title", "")))
        out.sort()
        return out
    except Exception:
        return []


def openai_rss():
    try:
        r = S.get("https://openai.com/news/rss.xml", timeout=25)
        root = ET.fromstring(r.content)
        rows = []
        for it in root.iter("item"):
            ti = it.findtext("title", "")
            pd = it.findtext("pubDate")
            if pd:
                try:
                    rows.append((pd, ti))
                except Exception:
                    pass
        return rows
    except Exception as e:
        print("openai rss err", e, file=sys.stderr)
        return []


print("=" * 120)
print("HACKER NEWS as the clock: first exact-match story vs first Russian Telegram post (UTC)")
print("=" * 120)
print("%-27s %-14s %-14s %-14s %s" % ("story", "HN 1st", "RU 1st", "RU lag", "HN title / RU channel"))
print("-" * 120)
res, lags = {}, []
for key, anchors in ANCHORS.items():
    h = hn(Q[key])
    pairs = sorted((datetime.fromisoformat(t + ":00+00:00"), c) for c, t in anchors)
    rt, chn = pairs[0]
    if h:
        ht, htitle = h[0]
        lag = (rt - ht).total_seconds() / 60
        f = lambda x: x.strftime("%m-%d %H:%M")
        print("%-27s %-14s %-14s %+9.0f min  %s | RU:@%s" % (key, f(ht), f(rt), lag, htitle[:44], chn))
        lags.append((lag, key))
    else:
        print("%-27s %-14s %-14s %-12s %s" % (key, "-- нет --", rt.strftime("%m-%d %H:%M"), "?", chn))
    res[key] = {"hn": [(t.isoformat(), ti) for t, ti in h[:5]],
                "ru": [(t.isoformat(), c) for t, c in pairs],
                "lag_min": round((rt - h[0][0]).total_seconds() / 60) if h else None}
    time.sleep(0.6)

lags.sort()
print("\n" + "=" * 74)
print("measured RU lag behind Hacker News:  n=%d" % len(lags))
for v, k in lags:
    print("   %-27s +%5.0f min" % (k, v))
if lags:
    print("   median +%.0f min   max +%.0f min" % (lags[len(lags)//2][0], lags[-1][0]))

print("\n" + "=" * 90)
print("OpenAI official news feed (raw, for manual check of release-time claims)")
print("=" * 90)
for pd, ti in openai_rss()[:12]:
    print("  ", pd, "|", ti[:78])

json.dump(res, open(D + "timeline_hn.json", "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)
