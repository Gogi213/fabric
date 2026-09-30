"""Сбор ЭЛЕМЕНТОВ фидов за последние N суток — вторая сторона сопоставления «пост ↔ источник».

Список источников — только те, что tools/feeds_probe.py признал живыми (или заведомо
рабочие API). Для каждого элемента: источник, категория, заголовок, анонс, ссылка, время.

Запуск:  python tools/feed_items.py [DAYS=5]  ->  data/feed_items.json
"""
import calendar, json, os, re, sys, time
from datetime import datetime, timedelta, timezone

import feedparser
import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "feed_items.json")
DAYS = float(sys.argv[1]) if len(sys.argv) > 1 else 5.0
NOW = datetime.now(timezone.utc)
SINCE = NOW - timedelta(days=DAYS)
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
S = requests.Session()
S.headers["User-Agent"] = UA

GH = "https://github.com/%s/releases.atom"
RSS = [
    # лаборатории / вендоры
    ("openai", "lab", "https://openai.com/news/rss.xml"),
    ("google_ai", "lab", "https://blog.google/technology/ai/rss/"),
    ("google_gemini", "lab", "https://blog.google/products/gemini/rss/"),
    ("deepmind", "lab", "https://deepmind.google/blog/rss.xml"),
    ("microsoft", "lab", "https://blogs.microsoft.com/feed/"),
    ("nvidia_dev", "lab", "https://developer.nvidia.com/blog/feed/"),
    ("mistral", "lab", "https://mistral.ai/rss.xml"),
    ("huggingface_blog", "lab", "https://huggingface.co/blog/feed.xml"),
    ("aws_ml", "lab", "https://aws.amazon.com/blogs/machine-learning/feed/"),
    ("apple_ml", "lab", "https://machinelearning.apple.com/rss.xml"),
    ("habr_yandex", "lab", "https://habr.com/ru/rss/companies/yandex/articles/"),
    ("habr_sber", "lab", "https://habr.com/ru/rss/companies/sberbank/articles/"),
    ("simonwillison", "lab", "https://simonwillison.net/atom/everything/"),
    ("the_decoder", "media_en", "https://the-decoder.com/feed/"),
    ("smol_ai", "agg", "https://news.smol.ai/rss.xml"),
    # код / модели
    ("gh_ollama", "code", GH % "ollama/ollama"),
    ("gh_llamacpp", "code", GH % "ggml-org/llama.cpp"),
    ("gh_vllm", "code", GH % "vllm-project/vllm"),
    ("gh_transformers", "code", GH % "huggingface/transformers"),
    ("gh_openai_python", "code", GH % "openai/openai-python"),
    ("gh_anthropic_sdk", "code", GH % "anthropics/anthropic-sdk-python"),
    ("gh_claude_code", "code", GH % "anthropics/claude-code"),
    ("gh_codex", "code", GH % "openai/codex"),
    ("arxiv_cs_ai", "code", "https://rss.arxiv.org/rss/cs.AI"),
    ("arxiv_cs_cl", "code", "https://rss.arxiv.org/rss/cs.CL"),
    # агрегаторы / сообщества
    ("techmeme", "agg", "https://www.techmeme.com/feed.xml"),
    ("lobsters", "agg", "https://lobste.rs/rss"),
    ("tldr_ai", "agg", "https://tldr.tech/api/rss/ai"),
    ("tldr_tech", "agg", "https://tldr.tech/api/rss/tech"),
    ("reddit_localllama", "agg", "https://www.reddit.com/r/LocalLLaMA/top/.rss?t=week&limit=100"),
    ("reddit_openai", "agg", "https://www.reddit.com/r/OpenAI/top/.rss?t=week&limit=100"),
    ("reddit_singularity", "agg", "https://www.reddit.com/r/singularity/top/.rss?t=week&limit=100"),
    ("reddit_technology", "agg", "https://www.reddit.com/r/technology/top/.rss?t=week&limit=100"),
    ("google_news_ai", "agg", "https://news.google.com/rss/search?q=AI+when:5d&hl=en-US&gl=US&ceid=US:en"),
    # СМИ EN
    ("techcrunch", "media_en", "https://techcrunch.com/feed/"),
    ("verge", "media_en", "https://www.theverge.com/rss/index.xml"),
    ("ars", "media_en", "https://feeds.arstechnica.com/arstechnica/index"),
    ("wired", "media_en", "https://www.wired.com/feed/rss"),
    ("venturebeat", "media_en", "https://venturebeat.com/feed/"),
    ("mittr", "media_en", "https://www.technologyreview.com/feed/"),
    ("register", "media_en", "https://www.theregister.com/headlines.atom"),
    ("bleepingcomputer", "media_en", "https://www.bleepingcomputer.com/feed/"),
    ("thehackernews", "media_en", "https://feeds.feedburner.com/TheHackersNews"),
    ("9to5mac", "media_en", "https://9to5mac.com/feed/"),
    ("9to5google", "media_en", "https://9to5google.com/feed/"),
    ("tomshardware", "media_en", "https://www.tomshardware.com/feeds/all"),
    ("engadget", "media_en", "https://www.engadget.com/rss.xml"),
    ("electrek", "media_en", "https://electrek.co/feed/"),
    ("gsmarena", "media_en", "https://www.gsmarena.com/rss-news-reviews.php3"),
    ("videocardz", "media_en", "https://videocardz.com/feed"),
    # СМИ RU
    ("habr_all", "media_ru", "https://habr.com/ru/rss/articles/"),
    ("habr_news", "media_ru", "https://habr.com/ru/rss/news/"),
    ("vcru", "media_ru", "https://vc.ru/rss"),
    ("3dnews", "media_ru", "https://3dnews.ru/news/rss/"),
    ("ixbt", "media_ru", "https://www.ixbt.com/export/news.rss"),
    ("tproger", "media_ru", "https://tproger.ru/feed"),
    ("overclockers", "media_ru", "https://overclockers.ru/rss/all.rss"),
    ("cnews", "media_ru", "https://www.cnews.ru/inc/rss/news.xml"),
    ("rb_ru", "media_ru", "https://rb.ru/feeds/all/"),
    ("lenta", "media_ru", "https://lenta.ru/rss/news"),
    ("rbc", "media_ru", "https://rssexport.rbc.ru/rbcnews/news/30/full.rss"),
    ("ria", "media_ru", "https://ria.ru/export/rss2/archive/index.xml"),
    ("tass", "media_ru", "https://tass.ru/rss/v2.xml"),
    ("interfax", "media_ru", "https://www.interfax.ru/rss.asp"),
    ("kommersant", "media_ru", "https://www.kommersant.ru/RSS/news.xml"),
    ("opennet", "media_ru", "https://www.opennet.ru/opennews/opennews_all.rss"),
    ("securitylab", "media_ru", "https://www.securitylab.ru/_services/export/rss/"),
    ("4pda", "media_ru", "https://4pda.to/feed/"),
]


def clean(s):
    s = re.sub(r"<[^>]+>", " ", s or "")
    return re.sub(r"\s+", " ", s).strip()


def ts(e):
    for k in ("published_parsed", "updated_parsed", "created_parsed"):
        v = e.get(k)
        if v:
            return datetime.fromtimestamp(calendar.timegm(v), timezone.utc)
    return None


def rss(src, cat, url):
    r = S.get(url, timeout=25)
    f = feedparser.parse(r.content)
    out = []
    for e in f.entries:
        t = ts(e)
        if not t or t < SINCE:
            continue
        out.append({"src": src, "cat": cat, "title": clean(e.get("title")),
                    "summary": clean(e.get("summary"))[:600], "link": e.get("link", ""),
                    "dt": t.isoformat()})
    return r.status_code, len(f.entries), out


def hn():
    """Hacker News: все истории окна, набравшие ≥ 30 очков (≈ всё, что видно на первых страницах)."""
    out, page = [], 0
    since = int(SINCE.timestamp())
    while True:
        r = S.get("https://hn.algolia.com/api/v1/search_by_date",
                  params={"tags": "story", "numericFilters": f"created_at_i>{since},points>=30",
                          "hitsPerPage": 1000, "page": page}, timeout=30)
        js = r.json()
        for h in js.get("hits", []):
            out.append({"src": "hackernews", "cat": "agg", "title": h.get("title") or "",
                        "summary": "", "link": h.get("url") or f"https://news.ycombinator.com/item?id={h['objectID']}",
                        "dt": datetime.fromtimestamp(h["created_at_i"], timezone.utc).isoformat(),
                        "points": h.get("points")})
        page += 1
        if page >= js.get("nbPages", 0) or page > 10:
            break
        time.sleep(1)
    return 200, len(out), out


def hf_papers():
    r = S.get("https://huggingface.co/api/daily_papers?limit=100", timeout=25)
    out = []
    for p in r.json():
        t = datetime.fromisoformat((p.get("publishedAt") or p["paper"]["publishedAt"]).replace("Z", "+00:00"))
        if t < SINCE:
            continue
        out.append({"src": "hf_daily_papers", "cat": "code", "title": p["paper"]["title"],
                    "summary": (p["paper"].get("summary") or "")[:600],
                    "link": f"https://huggingface.co/papers/{p['paper']['id']}", "dt": t.isoformat()})
    return r.status_code, len(out), out


if __name__ == "__main__":
    items, status = [], {}
    jobs = [(s, c, u) for s, c, u in RSS]
    for s, c, u in jobs:
        try:
            code, n_all, got = rss(s, c, u)
        except Exception as e:
            code, n_all, got = type(e).__name__, 0, []
        items += got
        status[s] = {"cat": c, "url": u, "http": code, "entries": n_all, "in_window": len(got)}
        print(f"  {s:22s} {str(code):>5s} всего {n_all:4d}  в окне {len(got):4d}", file=sys.stderr)
        time.sleep(0.7)
    for name, fn in (("hackernews", hn), ("hf_daily_papers", hf_papers)):
        try:
            code, n_all, got = fn()
        except Exception as e:
            code, n_all, got = type(e).__name__, 0, []
        items += got
        status[name] = {"cat": got[0]["cat"] if got else "", "http": code, "entries": n_all, "in_window": len(got)}
        print(f"  {name:22s} {str(code):>5s} в окне {len(got):4d}", file=sys.stderr)
    json.dump({"_meta": {"since": SINCE.isoformat(), "fetched": NOW.isoformat()},
               "status": status, "items": items},
              open(OUT, "w", encoding="utf-8"), ensure_ascii=False)
    print(f"saved {len(items)} items from {sum(1 for v in status.values() if v['in_window'])} sources", file=sys.stderr)
