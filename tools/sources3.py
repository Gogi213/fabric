import json, re, sys
from collections import Counter, defaultdict
from urllib.parse import urlparse

D = "C:/visual projects/parser/data/"
data = json.load(open(D + "links.json", encoding="utf-8"))

RU = ["whackdoor", "bugnotfeature", "technomedia", "exploitex", "naebnet",
      "trends", "tlive", "technomotel", "hiaimedia", "xor_journal", "ai_newz",
      "data_secrets", "seeallochnaya", "denissexy", "neuraldvig", "gptpublic",
      "rozetked", "d_code", "cgevent", "NeuralShit", "tproger",
      "ai_machinelearning_big_data"]
TG = re.compile(r"(?:t\.me|telegram\.me)/([A-Za-z0-9_]{3,})", re.I)
BOT = re.compile(r"(bot|_bot|bot_)", re.I)

# ---------- 1. forward map (the only declared source) ----------
print("=== 1. ПЕРЕСЛАНО ОТ — единственная декларация источника (2 недели) ===", file=sys.stderr)
fwd = defaultdict(Counter)
fwd_posts = []
for ch in RU:
    for p in data.get(ch, []):
        if not p["fwd_url"]:
            continue
        m = TG.search(p["fwd_url"])
        h = m.group(1) if m else p["fwd_name"]
        fwd[ch][h] += 1
        fwd_posts.append((ch, p["dt"], h, p["fwd_name"], p["text"][:110], p["fwd_url"]))
tot = sum(sum(v.values()) for v in fwd.values())
print(f"  всего форвардов у русских каналов: {tot}", file=sys.stderr)
for ch in RU:
    if not fwd[ch]:
        continue
    items = ", ".join(f"@{h}×{n}" for h, n in fwd[ch].most_common())
    print(f"  {ch:28s} {items}", file=sys.stderr)

# classify: news source vs advertiser
AD = re.compile(r"(альфа|alfabank| alfa|alfa_|vygodno|aaaa_|avito|немалы|beeline|mts|burger|ozon|setka|"
                r"mediyca|alfabank\.sale|Only)", re.I)
print("\n  --- форварды-НОВОСТИ (без рекламодателей) ---", file=sys.stderr)
news_fwd = [(c, d, h, t, u) for c, d, h, n, t, u in fwd_posts if not AD.search(h + " " + n)]
for c, d, h, n, t in news_fwd:
    print(f"    {c:22s} {d[:16]}  <- @{h:24s} {t[:70]}", file=sys.stderr)
print(f"\n  из {tot} форвардов новостных: {len(news_fwd)}, рекламных: {tot-len(news_fwd)}",
      file=sys.stderr)

# ---------- 2. inbound from other channels = the real upstream ----------
print("\n=== 2. ВХОДЯЩИЕ ССЫЛКИ: кто на кого ссылается ===", file=sys.stderr)
tg_by = defaultdict(Counter)
for ch in RU:
    for p in data.get(ch, []):
        for u in p["links"]:
            m = TG.search(u)
            if not m:
                continue
            h = m.group(1).lower()
            if h in (ch.lower(), "tehnochat") or BOT.search(h) or AD.search(h):
                continue
            tg_by[ch]["@" + m.group(1)] += 1
inb = Counter()
for c in tg_by:
    for h, n in tg_by[c].items():
        inb[h] += n
for h, n in inb.most_common(20):
    srcs = sorted(c for c in tg_by if tg_by[c][h] and c != h.lstrip("@"))
    print(f"  {h:28s} входящих={n:3d}  от: {','.join(srcs)}", file=sys.stderr)

# ---------- 3. genuine off-platform sources ----------
print("\n=== 3. ВНЕШНИЕ ПЕРВОИСТОЧНИКИ (без t.me и без своих сайтов) ===", file=sys.stderr)
SELF = {"kod.ru", "rozetked.me", "tprg.ru", "exploit.media", "dslab.tech"}
def rootdom(u):
    h = urlparse(u).netloc.lower()
    h = h[4:] if h.startswith("www.") else h
    p = h.split(".")
    return ".".join(p[-2:]) if len(p) >= 2 and not p[-2].isdigit() else h

BUCKET = [
    ("X / Twitter",      ("x.com", "twitter.com", "t.co")),
    ("GitHub (репо/код)",("github.com", "github.io")),
    ("Hugging Face",     ("huggingface.co",)),
    ("Блоги AI-лабораторий", ("openai.com", "anthropic.com", "claude.ai", "claude.com",
                              "blog.google", "deepmind.google", "qwen.ai", "ai.meta.com",
                              "mistral.ai", "x.ai", "perplexity.ai", "chatgpt.com")),
    ("arXiv / препринты",("arxiv.org",)),
    ("YouTube",          ("youtube.com", "youtu.be")),
    ("СМИ США/Европа",   ("reuters.com", "bloomberg.com", "cnbc.com", "cnn.com", "bbc.com",
                          "nytimes.com", "wsj.com", "theinformation.com", "businessinsider.com",
                          "technologyreview.com", "nature.com", "smh.com.au", "semafor.com",
                          "axios.com", "theguardian.com", "fortune.com", "wired.com", "ieee.org",
                          "sciencedaily.com", "newscientist.com", "phys.org", "space.com",
                          "tomshardware.com", "anandtech.com", "9to5mac.com", "macrumors.com",
                          "androidauthority.com", "xda-developers.com")),
    ("Российские СМИ",   ("rbc.ru", "ria.ru", "tass.ru", "iz.ru", "kommersant.ru", "lenta.ru",
                          "gazeta.ru", "rg.ru", "vedomosti.ru", "fontanka.ru", "vc.ru",
                          "habr.com", "cnn.com", "forbes.ru", "banki.ru", "eprussia.ru")),
    ("Reddit / HN / HN-like", ("reddit.com", "news.ycombinator.com", "lobste.rs")),
    ("Продукты (Apple/Google/MS/NVIDIA)", ("apple.com", "google.com", "microsoft.com",
                          "nvidia.com", "adobe.com", "figma.com", "notion.so")),
]
off = defaultdict(Counter)
for ch in RU:
    for p in data.get(ch, []):
        for u in p["links"]:
            if TG.search(u):
                continue
            d = rootdom(u)
            if not d or d in SELF or d in ("bit.ly", "u.to", "clck.ru", "tinyurl.com"):
                continue
            off[ch][d] += 1
grand = Counter()
for c in off:
    grand.update(off[c])
TOT = sum(grand.values())
buck = Counter()
unb = Counter()
for d, n in grand.items():
    hit = None
    for name, ds in BUCKET:
        if d in ds:
            hit = name
            break
    buck[hit or "прочее"] += n
    if not hit:
        unb[d] += n
print(f"  всего внешних ссылок (очищено): {TOT}\n", file=sys.stderr)
for k, v in buck.most_common():
    print(f"  {k:38s} {v:5d}  {v/TOT*100:5.1f}%", file=sys.stderr)
print(f"\n  --- не классифицировано, топ-25 ---", file=sys.stderr)
for d, n in unb.most_common(25):
    print(f"    {d:34s} {n:4d}", file=sys.stderr)

print("\n=== 4. ПРОФИЛЬ КАНАЛА: доля внешних первоисточников ===", file=sys.stderr)
for ch in RU:
    n = sum(off[ch].values())
    if not n:
        print(f"  {ch:28s} нет внешних ссылок", file=sys.stderr)
        continue
    top = ", ".join(f"{d}({k})" for d, k in off[ch].most_common(6))
    print(f"  {ch:28s} {n:4d} | {top}", file=sys.stderr)
