import requests
S = requests.Session()
S.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"})

TESTS = {
    "HackerNews API":  "https://hn.algolia.com/api/v1/search?query=Opus%205.5&tags=story",
    "arXiv API":       "http://export.arxiv.org/api/query?search_query=all:%22Claude+Opus%22&max_results=2",
    "Reddit JSON":     "https://www.reddit.com/search.json?q=Opus+5.5&sort=new&limit=2",
    "Reddit r/ChatGPT":"https://www.reddit.com/r/LocalLLaMA/new.json?limit=5",
    "Bluesky":         "https://public.api.bsky.app/xrpc/app.bsky.feed.searchPosts?q=Opus+5.5&limit=2",
    "TechCrunch RSS":  "https://techcrunch.com/feed/",
    "TheVerge RSS":    "https://www.theverge.com/rss/index.xml",
    "Ars RSS":         "https://feeds.arstechnica.com/arstechnica/index",
    "VentureBeat RSS": "https://venturebeat.com/feed/",
    "MITTR RSS":       "https://www.technologyreview.com/feed/",
    "HN RSS":          "https://hnrss.org/frontpage",
    "GoogleNews RSS":  "https://news.google.com/rss/search?q=%22Opus+5.5%22&hl=en-US",
    "OpenAI news":     "https://openai.com/news/rss.xml",
    "Anthropic news":  "https://www.anthropic.com/news",
    "X syndication":   "https://cdn.syndication.twimg.com/timeline/profile?screen_name=sama",
    "Nitter":          "https://nitter.net/sama/rss",
    "Mastodon":        "https://mastodon.social/api/v1/timeline/public",
    "YouTube RSS":     "https://www.youtube.com/feeds/videos.xml?channel_id=UCXZCOfdSJ3cQvAQT6eXQ6w",
}
for k, u in TESTS.items():
    try:
        r = S.get(u, timeout=20)
        ct = r.headers.get("content-type", "?")[:38]
        print("%-18s %-4s len=%-9d %s" % (k, r.status_code, len(r.content), ct))
    except Exception as e:
        print("%-18s ERR %s: %s" % (k, type(e).__name__, str(e)[:60]))
