#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
feeds_probe.py -- эмпирическая проверка фидов/источников новостей IT/AI.

Что делает: для каждого источника из SOURCES делает вежливые GET-запросы
(не чаще 1 запроса/сек на домен, UA обычного браузера, таймаут 20 с, без
ретраев), проверяет СОДЕРЖИМОЕ (а не только код ответа), разбирает элементы
и пишет сырые факты в data/feeds_probe.json:

  * HTTP: код, Content-Type, финальный URL, редиректы, размер, заголовки
    кэширования/лимитов, поддержка conditional GET (ETag/Last-Modified -> 304);
  * формат: rss2 / rss1 / atom / json / html / sitemap / ...; «HTML вместо ленты»,
    пустая лента, Cloudflare/DDoS-Guard/Akamai-челлендж, 403/429;
  * элементы: число, самое свежее/старое, возраст свежего (от момента запуска),
    медианный интервал, элементов за 24 ч / 7 сут;
  * ТОЧНОСТЬ ВРЕМЕНИ: есть ли секунды и часовой пояс, доля дата-без-времени,
    доля 00:00:00 (в сыром виде и в UTC), доля «круглых часов» (:00:00),
    доля нулевых секунд, самое частое время суток и его доля;
  * id/guid (покрытие, уникальность), ссылки, полный текст vs анонс vs заголовок;
  * ошибки сети: proxy_policy_denied (403/407 от egress-прокси) отличается от
    403/429 самого сайта; при сетевых ошибках к записи прикладывается срез
    /__agentproxy/status.

Запуск (из корня репозитория):
    python3 tools/feeds_probe.py                  # все источники
    python3 tools/feeds_probe.py --only openai_news,habr_all
    python3 tools/feeds_probe.py --group media_ru
    python3 tools/feeds_probe.py --list           # список источников
    python3 tools/feeds_probe.py --out data/feeds_probe.json --workers 12
    python3 tools/feeds_probe.py --latency 8      # + 8 минут повторного опроса быстрых лент (замер задержки)
    python3 tools/feeds_probe.py --no-crosscheck  # без сверки времени ленты с Hacker News

Зависимости: только requests (feedparser/bs4 НЕ нужны: разбор на xml.etree и
регулярках, чтобы видеть сырые строки дат, которые feedparser нормализует).
TLS-проверка всегда включена (используется REQUESTS_CA_BUNDLE/SSL_CERT_FILE из
окружения, т.е. CA-бандл прокси песочницы, либо системное хранилище).

Замечание о методе: основной прогон измеряет состояние ленты «сейчас». Он НЕ
измеряет задержку «событие -> появление в ленте»; для этого есть необязательный
режим --latency (повторный опрос ~20 быстрых лент, см. latency_experiment в JSON),
а также кросс-проверка времени ленты по первому посту того же URL на Hacker News
(crosschecks_vs_hn). Обе оценки приблизительны и описаны в самом JSON.
"""
from __future__ import annotations

import argparse
import collections
import concurrent.futures as cf
import datetime as dt
import email.utils
import html as htmllib
import json
import os
import platform
import re
import statistics
import sys
import threading
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = Path("data") / "feeds_probe.json"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
BASE_HEADERS = {
    "User-Agent": UA,
    "Accept": ("application/rss+xml, application/atom+xml, application/xml;q=0.9, "
               "text/xml;q=0.8, application/json;q=0.7, text/html;q=0.6, */*;q=0.5"),
    "Accept-Language": "en-US,en;q=0.9,ru;q=0.8",
}
NAV_HEADERS = {   # то, что шлёт обычный браузер при навигации (Meta AI отвечает 400 без Sec-Fetch-*)
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Sec-Fetch-Mode": "navigate", "Sec-Fetch-Site": "none", "Sec-Fetch-Dest": "document",
    "Upgrade-Insecure-Requests": "1",
}
HTML_KINDS = ("html", "anthropic_html", "telegram")
HOST_INTERVAL = {"reddit.com": 15.0, "arxiv.org": 3.1}   # арXiv просит >=3 с между запросами
TIMEOUT = 20            # секунд; и на соединение, и на чтение
WALL_LIMIT = 45         # общий потолок времени на одно скачивание, сек
MAX_BYTES = 6_000_000   # не качаем больше
MIN_INTERVAL = 1.05     # сек между запросами к одному домену
SAMPLE_N = 4            # сколько свежих элементов класть в sample
TIMES_CAP = 200         # сколько меток времени хранить для перепроверки

NOW = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)


# --------------------------------------------------------------------------
# Список источников
# --------------------------------------------------------------------------
def S(id, group, name, url, kind="feed", **kw):
    d = dict(id=id, group=group, name=name, url=url, kind=kind)
    d.update(kw)
    return d


GH = "https://github.com/%s/releases.atom"
PYPI = "https://pypi.org/rss/project/%s/releases.xml"
OLS = "https://raw.githubusercontent.com/Olshansk/rss-feeds/main/feeds/%s"
SOURCES = [
    # --- блоги лабораторий / вендоров -------------------------------------
    S("openai_news", "lab", "OpenAI News RSS", "https://openai.com/news/rss.xml"),
    S("anthropic_news_html", "lab", "Anthropic /news (HTML; publishedOn из встроенных Next.js-данных)",
      "https://www.anthropic.com/news", kind="anthropic_html"),
    S("anthropic_rss_guess", "lab", "Anthropic /rss.xml (проверка: официальной ленты нет?)",
      "https://www.anthropic.com/rss.xml"),
    S("anthropic_sitemap", "lab", "Anthropic sitemap.xml (только /news/; lastmod = правка страницы)",
      "https://www.anthropic.com/sitemap.xml", kind="sitemap", url_filter="/news/"),
    S("anthropic_community_rss", "lab", "Anthropic News (community-лента Olshansk/rss-feeds, raw.githubusercontent)",
      OLS % "feed_anthropic_news.xml"),
    S("claude_status", "lab", "Claude status (incidents)", "https://status.claude.com/history.rss"),
    S("claude_platform_release_notes", "lab", "Claude Platform release notes (HTML, даты текстом)",
      "https://platform.claude.com/docs/en/release-notes/overview", kind="html"),
    S("npm_claude_code", "lab", "npm @anthropic-ai/claude-code (поле time)",
      "https://registry.npmjs.org/@anthropic-ai/claude-code", kind="npm"),
    S("google_blog_ai", "lab", "blog.google / AI", "https://blog.google/technology/ai/rss/"),
    S("google_blog_gemini", "lab", "blog.google / Gemini", "https://blog.google/products/gemini/rss/"),
    S("deepmind_blog", "lab", "Google DeepMind blog", "https://deepmind.google/blog/rss.xml"),
    S("meta_ai_blog", "lab", "Meta AI blog (HTML)", "https://ai.meta.com/blog/", kind="html"),
    S("ms_ai_blog_old", "lab", "blogs.microsoft.com/ai/feed (старый адрес)", "https://blogs.microsoft.com/ai/feed/"),
    S("ms_official_blog", "lab", "The Official Microsoft Blog", "https://blogs.microsoft.com/feed/"),
    S("nvidia_dev_blog", "lab", "NVIDIA Technical Blog", "https://developer.nvidia.com/blog/feed/"),
    S("mistral_news_rss", "lab", "Mistral news RSS (mistral.ai/rss.xml -> /news/rss)", "https://mistral.ai/rss.xml"),
    S("qwen_blog_old", "lab", "Qwen blog (qwenlm.github.io, старый)", "https://qwenlm.github.io/blog/index.xml"),
    S("hf_blog", "lab", "Hugging Face blog", "https://huggingface.co/blog/feed.xml"),
    S("xai_news", "lab", "xAI news (HTML)", "https://x.ai/news", kind="html"),
    S("xai_community_rss", "lab", "xAI News (community-лента Olshansk/rss-feeds)", OLS % "feed_xainews.xml"),
    S("aws_ml_blog", "lab", "AWS Machine Learning blog", "https://aws.amazon.com/blogs/machine-learning/feed/"),
    S("azure_blog", "lab", "Azure blog", "https://azure.microsoft.com/en-us/blog/feed/"),
    S("apple_ml", "lab", "Apple Machine Learning Research", "https://machinelearning.apple.com/rss.xml"),
    S("habr_yandex", "lab", "Хабр: блог Яндекса", "https://habr.com/ru/rss/companies/yandex/articles/"),
    S("yandex_cloud_blog", "lab", "Yandex Cloud blog (HTML)", "https://yandex.cloud/ru/blog", kind="html"),
    S("habr_sber", "lab", "Хабр: блог Сбера", "https://habr.com/ru/rss/companies/sberbank/articles/"),
    S("simonwillison", "lab", "Simon Willison's Weblog", "https://simonwillison.net/atom/everything/"),
    S("the_decoder", "lab", "The Decoder (AI-новости)", "https://the-decoder.com/feed/"),
    S("smol_ai", "lab", "smol.ai AI News (дайджест)", "https://news.smol.ai/rss.xml"),

    # --- код и модели -----------------------------------------------------
    S("gh_ollama", "code", "GitHub releases.atom ollama/ollama", GH % "ollama/ollama"),
    S("gh_openai_python", "code", "GitHub releases.atom openai/openai-python", GH % "openai/openai-python"),
    S("gh_llamacpp", "code", "GitHub releases.atom ggml-org/llama.cpp", GH % "ggml-org/llama.cpp"),
    S("pypi_openai", "code", "PyPI RSS: openai (замена GitHub releases)", PYPI % "openai"),
    S("pypi_anthropic", "code", "PyPI RSS: anthropic", PYPI % "anthropic"),
    S("pypi_vllm", "code", "PyPI RSS: vllm", PYPI % "vllm"),
    S("hf_daily_papers", "code", "HF Daily Papers API", "https://huggingface.co/api/daily_papers?limit=30",
      kind="hf_papers"),
    S("hf_models_trending", "code", "HF models, sort=trendingScore (API)",
      "https://huggingface.co/api/models?sort=trendingScore&limit=30", kind="hf_models"),
    S("hf_models_new", "code", "HF models, sort=createdAt (API)",
      "https://huggingface.co/api/models?sort=createdAt&direction=-1&limit=30", kind="hf_models"),
    S("arxiv_api_cs_ai", "code", "arXiv API cs.AI (по submittedDate)",
      "https://export.arxiv.org/api/query?search_query=cat:cs.AI&sortBy=submittedDate&sortOrder=descending&max_results=50"),
    S("arxiv_rss_cs_ai", "code", "arXiv RSS cs.AI", "https://rss.arxiv.org/rss/cs.AI"),
    S("arxiv_rss_cs_cl", "code", "arXiv RSS cs.CL", "https://rss.arxiv.org/rss/cs.CL"),
    S("arxiv_rss_cs_lg", "code", "arXiv RSS cs.LG", "https://rss.arxiv.org/rss/cs.LG"),

    # --- агрегаторы / сообщества -----------------------------------------
    S("hn_firebase", "agg", "Hacker News Firebase (newstories + 12 item)",
      "https://hacker-news.firebaseio.com/v0/newstories.json", kind="hn_firebase"),
    S("hn_algolia", "agg", "Hacker News Algolia search_by_date",
      "https://hn.algolia.com/api/v1/search_by_date?tags=story&hitsPerPage=50", kind="hn_algolia"),
    S("reddit_rss_localllama", "agg", "Reddit r/LocalLLaMA .rss", "https://www.reddit.com/r/LocalLLaMA/new/.rss?limit=50"),
    S("reddit_rss_machinelearning", "agg", "Reddit r/MachineLearning .rss", "https://www.reddit.com/r/MachineLearning/new/.rss?limit=50"),
    S("reddit_rss_openai", "agg", "Reddit r/OpenAI .rss", "https://www.reddit.com/r/OpenAI/new/.rss?limit=50"),
    S("reddit_rss_singularity", "agg", "Reddit r/singularity .rss", "https://www.reddit.com/r/singularity/new/.rss?limit=50"),
    S("reddit_json_localllama", "agg", "Reddit r/LocalLLaMA .json (последним: 403-ответ не должен «отравлять» RSS-квоту)",
      "https://www.reddit.com/r/LocalLLaMA/new.json?limit=50", kind="reddit_json"),
    S("lobsters", "agg", "lobste.rs /rss", "https://lobste.rs/rss"),
    S("techmeme", "agg", "Techmeme feed.xml", "https://www.techmeme.com/feed.xml"),
    S("tldr_ai", "agg", "TLDR AI (tldr.tech/api/rss/ai)", "https://tldr.tech/api/rss/ai"),
    S("producthunt", "agg", "Product Hunt feed", "https://www.producthunt.com/feed"),
    S("bsky_search", "agg", "Bluesky public API searchPosts",
      "https://public.api.bsky.app/xrpc/app.bsky.feed.searchPosts?q=openai&sort=latest&limit=50", kind="bsky"),
    S("bsky_author", "agg", "Bluesky public API getAuthorFeed (simonwillison.net)",
      "https://public.api.bsky.app/xrpc/app.bsky.feed.getAuthorFeed?actor=simonwillison.net&limit=50&filter=posts_no_replies",
      kind="bsky"),
    S("bsky_rss", "agg", "Bluesky профиль как RSS (bsky.app/profile/.../rss)",
      "https://bsky.app/profile/simonwillison.net/rss"),
    S("mastodon_tag_rss", "agg", "Mastodon mastodon.social/tags/ai.rss", "https://mastodon.social/tags/ai.rss"),
    S("mastodon_tag_api", "agg", "Mastodon API timelines/tag/ai", "https://mastodon.social/api/v1/timelines/tag/ai?limit=40",
      kind="mastodon"),
    S("mastodon_public_api", "agg", "Mastodon API timelines/public",
      "https://mastodon.social/api/v1/timelines/public?limit=40", kind="mastodon"),
    S("nitter_net", "agg", "Nitter nitter.net/sama/rss", "https://nitter.net/sama/rss"),
    S("xcancel", "agg", "Nitter-зеркало xcancel.com/sama/rss", "https://xcancel.com/sama/rss"),
    S("x_syndication", "agg", "X syndication timeline-profile (cdn.syndication.twimg.com)",
      "https://cdn.syndication.twimg.com/timeline/profile?screen_name=sama", kind="html"),
    S("x_com", "agg", "x.com/sama без логина (HTML-оболочка?)", "https://x.com/sama", kind="html"),
    S("gnews_openai", "agg", "Google News RSS (OpenAI, when:1d)",
      "https://news.google.com/rss/search?q=OpenAI+when:1d&hl=en-US&gl=US&ceid=US:en"),
    S("gnews_quoted_nowhen", "agg", "Google News RSS (запрос как в прежнем пробнике: \"Claude Opus\", без when:)",
      "https://news.google.com/rss/search?q=%22Claude+Opus%22&hl=en-US"),

    # --- англоязычные СМИ -------------------------------------------------
    S("techcrunch_all", "media_en", "TechCrunch (всё)", "https://techcrunch.com/feed/"),
    S("techcrunch_ai", "media_en", "TechCrunch / AI", "https://techcrunch.com/category/artificial-intelligence/feed/"),
    S("verge_all", "media_en", "The Verge (всё)", "https://www.theverge.com/rss/index.xml"),
    S("verge_ai", "media_en", "The Verge / AI", "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml"),
    S("ars_all", "media_en", "Ars Technica", "https://feeds.arstechnica.com/arstechnica/index"),
    S("wired_all", "media_en", "Wired", "https://www.wired.com/feed/rss"),
    S("venturebeat_all", "media_en", "VentureBeat", "https://venturebeat.com/feed/"),
    S("mittr", "media_en", "MIT Technology Review", "https://www.technologyreview.com/feed/"),
    S("register", "media_en", "The Register", "https://www.theregister.com/headlines.atom"),
    S("bleepingcomputer", "media_en", "BleepingComputer", "https://www.bleepingcomputer.com/feed/"),
    S("thehackernews", "media_en", "The Hacker News", "https://feeds.feedburner.com/TheHackersNews"),
    S("9to5mac", "media_en", "9to5Mac", "https://9to5mac.com/feed/"),
    S("9to5google", "media_en", "9to5Google", "https://9to5google.com/feed/"),
    S("tomshardware", "media_en", "Tom's Hardware", "https://www.tomshardware.com/feeds/all"),
    S("engadget", "media_en", "Engadget", "https://www.engadget.com/rss.xml"),

    # --- русскоязычные ----------------------------------------------------
    S("habr_all", "media_ru", "Хабр: все статьи", "https://habr.com/ru/rss/articles/"),
    S("habr_ai", "media_ru", "Хабр: хаб «Искусственный интеллект»", "https://habr.com/ru/rss/hubs/artificial_intelligence/articles/"),
    S("habr_ml", "media_ru", "Хабр: хаб «Машинное обучение»", "https://habr.com/ru/rss/hubs/machine_learning/articles/"),
    S("vcru", "media_ru", "vc.ru", "https://vc.ru/rss"),
    S("3dnews", "media_ru", "3DNews: новости", "https://3dnews.ru/news/rss/"),
    S("ixbt_news", "media_ru", "iXBT: новости", "https://www.ixbt.com/export/news.rss"),
    S("tproger", "media_ru", "Tproger", "https://tproger.ru/feed"),
    S("rozetked", "media_ru", "Rozetked", "https://rozetked.me/turbo"),
    S("overclockers", "media_ru", "Overclockers.ru", "https://overclockers.ru/rss/all.rss"),
    S("cnews", "media_ru", "CNews", "https://www.cnews.ru/inc/rss/news.xml"),
    S("rb_ru", "media_ru", "rb.ru", "https://rb.ru/feeds/all/"),
    S("forklog", "media_ru", "ForkLog", "https://forklog.com/feed"),
    S("lenta", "media_ru", "Lenta.ru: новости", "https://lenta.ru/rss/news"),
    S("rbc", "media_ru", "РБК: новости", "https://rssexport.rbc.ru/rbcnews/news/30/full.rss"),
    S("opennet", "media_ru", "OpenNet", "https://www.opennet.ru/opennews/opennews_all.rss"),

    # --- Telegram web-preview ---------------------------------------------
    S("tg_whackdoor", "telegram", "t.me/s/whackdoor", "https://t.me/s/whackdoor", kind="telegram"),
    S("tg_xor_journal", "telegram", "t.me/s/xor_journal", "https://t.me/s/xor_journal", kind="telegram"),
    S("tg_rozetked", "telegram", "t.me/s/rozetked", "https://t.me/s/rozetked", kind="telegram"),
    S("tg_data_secrets", "telegram", "t.me/s/data_secrets", "https://t.me/s/data_secrets", kind="telegram"),
]

# Кросс-проверка времени ленты по HN (earliest submission того же URL): id источника -> домен для Algolia
HN_CROSSCHECK = {
    "openai_news": "openai.com",
    "anthropic_news_html": "anthropic.com",
    "google_blog_ai": "blog.google",
    "hf_blog": "huggingface.co",
}


# Источники для необязательного замера задержки «время в ленте -> первое появление у нас» (--latency)
LATENCY_IDS = ["hn_algolia", "habr_all", "habr_ai", "lenta", "rbc", "ixbt_news", "overclockers", "3dnews",
               "rozetked", "cnews", "9to5google", "techcrunch_all", "techmeme", "gnews_openai",
               "mastodon_tag_rss", "tg_xor_journal", "tg_data_secrets", "tg_rozetked", "tg_whackdoor",
               "hf_models_new", "register", "opennet"]


# --------------------------------------------------------------------------
# Вежливость: не чаще 1 запроса/сек на домен
# --------------------------------------------------------------------------
_throttle_lock = threading.Lock()
_throttle_last: dict[str, float] = {}
_throttle_keylocks: dict[str, threading.Lock] = collections.defaultdict(threading.Lock)


def host_key(url: str) -> str:
    h = (urlparse(url).hostname or "").lower()
    parts = h.split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else h


def throttle(url: str):
    k = host_key(url)
    with _throttle_lock:
        lk = _throttle_keylocks[k]
    with lk:
        wait = HOST_INTERVAL.get(k, MIN_INTERVAL) - (time.monotonic() - _throttle_last.get(k, 0.0))
        if wait > 0:
            time.sleep(wait)
        _throttle_last[k] = time.monotonic()


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------
KEEP_HEADERS = ("server", "content-type", "content-encoding", "cache-control", "etag",
                "last-modified", "age", "expires", "date", "retry-after", "via",
                "x-cache", "cf-ray", "cf-mitigated", "cf-cache-status", "x-ratelimit-remaining",
                "x-ratelimit-limit", "x-ratelimit-reset", "ratelimit-remaining", "x-served-by",
                "x-vercel-cache", "x-vercel-mitigated", "x-github-request-id", "x-amz-cf-pop", "cdn-cache")


class Resp:
    def __init__(self):
        self.status = None
        self.url = None
        self.history = []
        self.headers = {}
        self.body = b""
        self.truncated = False
        self.elapsed = None
        self.error = None          # текст ошибки
        self.error_class = None    # см. classify_exception
        self.first_error = None    # ошибка первой попытки, если был повтор


def classify_exception(e: Exception) -> str:
    s = "%s %s" % (type(e).__name__, e)
    if isinstance(e, requests.exceptions.ProxyError):
        if re.search(r"\b(403|407)\b", s):
            return "proxy_policy_denied"
        return "proxy_error"
    if isinstance(e, requests.exceptions.SSLError):
        return "tls_error"
    if isinstance(e, (requests.exceptions.ConnectTimeout, requests.exceptions.ReadTimeout,
                      requests.exceptions.Timeout)):
        return "timeout"
    if isinstance(e, requests.exceptions.ChunkedEncodingError) or "Response ended prematurely" in s:
        return "truncated_stream"
    if isinstance(e, requests.exceptions.TooManyRedirects):
        return "redirect_loop"
    if re.search(r"Name or service not known|NameResolution|getaddrinfo|Temporary failure in name", s):
        return "dns_error"
    if re.search(r"reset by peer|RemoteDisconnected|Connection aborted|ConnectionReset|Connection ended", s):
        return "connection_reset"
    if isinstance(e, requests.exceptions.ConnectionError):
        return "connection_error"
    return "other_error"


class Fetcher:
    """Одна сессия на источник (изолированные cookie), с троттлингом по домену."""

    def __init__(self, nav=False):
        self.s = requests.Session()
        self.s.headers.update(BASE_HEADERS)
        if nav:
            self.s.headers.update(NAV_HEADERS)
        self.requests_made = 0
        self.retried = None

    def get(self, url: str, headers: dict | None = None, max_bytes: int = MAX_BYTES) -> Resp:
        r = self._get(url, headers, max_bytes)
        # один повтор ТОЛЬКО при транзиентной сетевой ошибке (не при HTTP-ответе, не при 403/429)
        if r.error_class in ("timeout", "connection_reset", "tls_error", "connection_error",
                             "truncated_stream") and self.retried is None:
            self.retried = "%s -> retry" % r.error_class
            time.sleep(3)
            r2 = self._get(url, headers, max_bytes)
            r2.first_error = r.error
            return r2
        return r

    def _get(self, url: str, headers: dict | None, max_bytes: int) -> Resp:
        throttle(url)
        self.requests_made += 1
        r = Resp()
        t0 = time.monotonic()
        try:
            resp = self.s.get(url, headers=headers or {}, timeout=TIMEOUT, stream=True,
                              allow_redirects=True)
            r.status = resp.status_code
            r.url = resp.url
            r.history = [(h.status_code, h.url) for h in resp.history]
            r.headers = {k.lower(): v for k, v in resp.headers.items()}
            chunks, total = [], 0
            for ch in resp.iter_content(65536):
                chunks.append(ch)
                total += len(ch)
                if total >= max_bytes:
                    r.truncated = True
                    break
                if time.monotonic() - t0 > WALL_LIMIT:
                    r.truncated = True
                    r.error = "wall time limit %ss" % WALL_LIMIT
                    break
            resp.close()
            r.body = b"".join(chunks)
        except Exception as e:  # noqa: BLE001
            r.error = "%s: %s" % (type(e).__name__, str(e)[:300])
            r.error_class = classify_exception(e)
            r.url = r.url or url
        r.elapsed = round(time.monotonic() - t0, 2)
        return r


def proxy_status() -> dict | None:
    base = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    if not base:
        return None
    try:
        r = requests.get(base.rstrip("/") + "/__agentproxy/status", timeout=5)
        return r.json()
    except Exception:  # noqa: BLE001
        return None


# --------------------------------------------------------------------------
# Даты и точность времени
# --------------------------------------------------------------------------
MONTHS = {m: i for i, m in enumerate(
    "jan feb mar apr may jun jul aug sep oct nov dec".split(), 1)}
TZ_ABBR = {"GMT": 0, "UT": 0, "UTC": 0, "Z": 0, "EST": -300, "EDT": -240, "CST": -360,
           "CDT": -300, "MST": -420, "MDT": -360, "PST": -480, "PDT": -420, "MSK": 180,
           "CET": 60, "CEST": 120, "BST": 60, "JST": 540, "IST": 330}
ISO_RE = re.compile(
    r"(\d{4})-(\d{2})-(\d{2})(?:[T\s]+(\d{2}):(\d{2})(?::(\d{2}))?(?:[.,]\d+)?)?"
    r"\s*(Z|UTC|GMT|[+-]\d{2}:?\d{2})?")
TEXTDATE_RE = re.compile(
    r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+(\d{1,2}),?\s+(20\d\d)\b")
RFC_RE = re.compile(
    r"(?:[A-Za-z]{3,9},?\s+)?(\d{1,2})[\s-]+([A-Za-z]{3,9})\.?[\s-]+(\d{2,4})"
    r"(?:[,\s]+(\d{1,2}):(\d{2})(?::(\d{2}))?)?\s*([A-Za-z]{1,4}|[+-]\d{2}:?\d{2})?")


def _tz_minutes(tok):
    if not tok:
        return None
    tok = tok.strip()
    m = re.fullmatch(r"([+-])(\d{2}):?(\d{2})", tok)
    if m:
        v = int(m.group(2)) * 60 + int(m.group(3))
        return -v if m.group(1) == "-" else v
    return TZ_ABBR.get(tok.upper())


def parse_date(raw):
    """-> dict(dt, raw_hms, has_tz, has_sec, date_only) или None."""
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        try:
            d = dt.datetime.fromtimestamp(float(raw), dt.timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
        return dict(dt=d.replace(microsecond=0), raw_hms=(d.hour, d.minute, d.second),
                    has_tz=True, has_sec=True, date_only=False)
    s = str(raw).strip()
    if not s:
        return None
    y = mo = d_ = h = mi = sec = None
    tz = None
    mt = TEXTDATE_RE.fullmatch(s)
    if mt:   # «September 30, 2026» -- только дата
        try:
            d = dt.datetime(int(mt.group(3)), MONTHS[mt.group(1).lower()], int(mt.group(2)), tzinfo=dt.timezone.utc)
        except ValueError:
            return None
        return dict(dt=d, raw_hms=(0, 0, 0), has_tz=False, has_sec=False, date_only=True)
    m = ISO_RE.match(s) or ISO_RE.search(s)
    if m and (m.start() == 0 or not RFC_RE.match(s)):
        y, mo, d_ = int(m.group(1)), int(m.group(2)), int(m.group(3))
        h = int(m.group(4)) if m.group(4) else None
        mi = int(m.group(5)) if m.group(5) else None
        sec = int(m.group(6)) if m.group(6) else None
        tz = _tz_minutes(m.group(7))
    else:
        m = RFC_RE.search(s)
        if m and m.group(2)[:3].lower() in MONTHS:
            d_, mo = int(m.group(1)), MONTHS[m.group(2)[:3].lower()]
            y = int(m.group(3))
            if y < 100:
                y += 2000 if y < 70 else 1900
            h = int(m.group(4)) if m.group(4) else None
            mi = int(m.group(5)) if m.group(5) else None
            sec = int(m.group(6)) if m.group(6) else None
            tz = _tz_minutes(m.group(7))
        else:
            try:
                d = email.utils.parsedate_to_datetime(s)
            except Exception:  # noqa: BLE001
                return None
            if d is None:
                return None
            has_tz = d.tzinfo is not None
            if not has_tz:
                d = d.replace(tzinfo=dt.timezone.utc)
            return dict(dt=d.astimezone(dt.timezone.utc), raw_hms=(d.hour, d.minute, d.second),
                        has_tz=has_tz, has_sec=True, date_only=False)
    date_only = h is None
    try:
        local = dt.datetime(y, mo, d_, h or 0, mi or 0, sec or 0)
    except ValueError:
        return None
    off = tz if tz is not None else 0
    utc = (local - dt.timedelta(minutes=off)).replace(tzinfo=dt.timezone.utc)
    return dict(dt=utc, raw_hms=(h or 0, mi or 0, sec or 0), has_tz=tz is not None,
                has_sec=sec is not None, date_only=date_only)


def share(k, n):
    return round(k / n, 3) if n else None


def precision_stats(pds):
    """pds: список результатов parse_date (не None)."""
    n = len(pds)
    if not n:
        return None
    c = collections.Counter()
    tod = collections.Counter()
    for p in pds:
        u = p["dt"]
        rh = p["raw_hms"]
        if p["date_only"]:
            c["date_only"] += 1
        if not p["has_tz"]:
            c["no_tz"] += 1
        if not p["has_sec"]:
            c["no_sec_field"] += 1
        if rh == (0, 0, 0):
            c["mid_raw"] += 1
        if (u.hour, u.minute, u.second) == (0, 0, 0):
            c["mid_utc"] += 1
        if rh[1] == 0 and rh[2] == 0:
            c["round_hour_raw"] += 1
        if u.minute == 0 and u.second == 0:
            c["round_hour_utc"] += 1
        if u.minute in (0, 30) and u.second == 0:
            c["round_half_hour_utc"] += 1
        if u.second == 0:
            c["zero_sec_utc"] += 1
        tod["%02d:%02d:%02d" % (u.hour, u.minute, u.second)] += 1
    top, topn = tod.most_common(1)[0]
    st = {
        "n": n,
        "share_date_only": share(c["date_only"], n),
        "share_no_tz": share(c["no_tz"], n),
        "share_no_seconds_in_string": share(c["no_sec_field"], n),
        "share_midnight_raw": share(c["mid_raw"], n),
        "share_midnight_utc": share(c["mid_utc"], n),
        "share_round_hour_raw": share(c["round_hour_raw"], n),
        "share_round_hour_utc": share(c["round_hour_utc"], n),
        "share_round_half_hour_utc": share(c["round_half_hour_utc"], n),
        "share_zero_seconds_utc": share(c["zero_sec_utc"], n),
        "tod_mode_utc": top,
        "tod_mode_share": share(topn, n),
        "tod_distinct": len(tod),
        "baseline_random_round_hour": round(1 / 3600, 4),
        "baseline_random_zero_sec": round(1 / 60, 3),
    }
    mid = max(st["share_midnight_raw"], st["share_midnight_utc"])
    rnd = max(st["share_round_hour_raw"], st["share_round_hour_utc"])
    if st["share_date_only"] >= 0.5:
        cls = "date_only"
    elif mid >= 0.5:
        cls = "midnight_stub"
    elif n >= 3 and st["tod_mode_share"] >= 0.5:
        cls = "constant_time"      # одно и то же время суток у большинства (напр. 05:44:39)
    elif rnd >= 0.5:
        cls = "hour_rounded"
    elif st["share_zero_seconds_utc"] >= 0.8:
        cls = "minute_precision"
    else:
        cls = "second_precision"
    st["class"] = cls
    if n < 8:
        st["low_n"] = True
    return st


# --------------------------------------------------------------------------
# Элементы и их статистика
# --------------------------------------------------------------------------
def strip_html(s: str) -> str:
    if not s:
        return ""
    s = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", s, flags=re.S | re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    s = htmllib.unescape(s)
    return re.sub(r"\s+", " ", s).strip()


def mk_item(id=None, title=None, link=None, date_raw=None, date_field=None, body_len=None,
            full=None):
    return dict(id=id, title=(title or "").strip() or None, link=link, date_raw=date_raw,
                date_field=date_field, body_len=body_len, full=full)


def id_kind(i):
    i = str(i)
    if re.match(r"https?://", i):
        return "url"
    if re.fullmatch(r"\d+", i):
        return "numeric"
    if i.startswith("tag:"):
        return "tag_uri"
    if i.startswith("at://"):
        return "at_uri"
    return "opaque"


def analyze_items(items, now):
    out = {"n_items": len(items)}
    if not items:
        return out
    parsed = []
    unparsed = []
    for it in items:
        p = parse_date(it["date_raw"]) if it["date_raw"] is not None else None
        it["_p"] = p
        if p:
            parsed.append(p)
        elif it["date_raw"] is not None:
            unparsed.append(str(it["date_raw"])[:60])
    out["n_with_date"] = len(parsed)
    out["n_no_date_field"] = sum(1 for it in items if it["date_raw"] is None)
    if unparsed:
        out["n_unparsed_dates"] = len(unparsed)
        out["unparsed_examples"] = unparsed[:3]
    # --- время ---
    if parsed:
        ts_all = sorted((p["dt"] for p in parsed), reverse=True)
        out["n_future_gt10min"] = sum(1 for t in ts_all if (t - now).total_seconds() > 600)
        # будущие даты (анонсы, дедлайны deprecation, ошибки ленты) исключаем из расчёта свежести
        ts = [t for t in ts_all if (t - now).total_seconds() <= 600] or ts_all
        if out["n_future_gt10min"]:
            out["newest_any_utc_incl_future"] = ts_all[0].isoformat()
        newest, oldest = ts[0], ts[-1]
        out["newest_utc"] = newest.isoformat()
        out["oldest_utc"] = oldest.isoformat()
        out["newest_age_min"] = round((now - newest).total_seconds() / 60, 1)
        out["span_days"] = round((newest - oldest).total_seconds() / 86400, 2)
        gaps = [(a - b).total_seconds() / 60 for a, b in zip(ts, ts[1:])]
        nz = [g for g in gaps if g > 0]
        out["median_gap_min"] = round(statistics.median(gaps), 1) if gaps else None
        out["median_gap_min_nonzero"] = round(statistics.median(nz), 1) if nz else None
        out["n_same_timestamp_pairs"] = sum(1 for g in gaps if g == 0)
        if out["span_days"] and out["span_days"] > 0:
            out["items_per_day"] = round((len(ts) - 1) / out["span_days"], 2)
        out["n_last_24h"] = sum(1 for t in ts if (now - t).total_seconds() <= 86400)
        out["n_last_7d"] = sum(1 for t in ts if (now - t).total_seconds() <= 7 * 86400)
        out["n_last_30d"] = sum(1 for t in ts if (now - t).total_seconds() <= 30 * 86400)
        # порядок в исходной ленте
        seq = [it["_p"]["dt"] for it in items if it["_p"]]
        if len(seq) > 1:
            desc = sum(1 for a, b in zip(seq, seq[1:]) if a >= b)
            asc = sum(1 for a, b in zip(seq, seq[1:]) if a <= b)
            out["order"] = ("newest_first" if desc >= 0.9 * (len(seq) - 1) else
                            "oldest_first" if asc >= 0.9 * (len(seq) - 1) else "mixed")
        out["precision"] = precision_stats(parsed)
        # то же на 30 самых свежих (старые записи могут быть «заглушками» иначе)
        newest30 = sorted((p for p in parsed), key=lambda p: p["dt"], reverse=True)[:30]
        if len(parsed) > 30:
            out["precision_newest30"] = precision_stats(newest30)
        # итоговый класс -- по самым свежим 30 (для мониторинга важно поведение ленты СЕЙЧАС)
        out["time_class"] = (out.get("precision_newest30") or out["precision"])["class"]
        out["time_class_full_history"] = out["precision"]["class"]
        out["date_fields_used"] = dict(collections.Counter(
            it["date_field"] for it in items if it["date_field"]))
        out["date_format_examples"] = [str(it["date_raw"])[:40] for it in items[:2] if it["date_raw"] is not None]
        out["times_utc"] = [t.strftime("%Y-%m-%dT%H:%M:%SZ") for t in ts[:TIMES_CAP]]
    # --- id / ссылки ---
    ids = [str(it["id"]) for it in items if it["id"] not in (None, "")]
    out["id_coverage"] = share(len(ids), len(items))
    out["id_unique_share"] = share(len(set(ids)), len(ids)) if ids else None
    if ids:
        out["id_kind"] = collections.Counter(id_kind(i) for i in ids).most_common(1)[0][0]
    out["link_coverage"] = share(sum(1 for it in items if it["link"]), len(items))
    out["stable_key_coverage"] = share(sum(1 for it in items if it["id"] not in (None, "") or it["link"]), len(items))
    out["title_coverage"] = share(sum(1 for it in items if it["title"]), len(items))
    # --- текст ---
    lens = [it["body_len"] for it in items if it["body_len"] is not None]
    if lens:
        med = statistics.median(lens)
        out["median_body_chars"] = int(med)
        out["share_full_content_tag"] = share(sum(1 for it in items if it["full"]), len(items))
        out["text_mode"] = ("full" if (out["share_full_content_tag"] or 0) >= 0.5 and med >= 800
                            else "full_or_long" if med >= 1500
                            else "excerpt" if med >= 40 else "title_only")
    else:
        out["text_mode"] = "title_only"
    # --- sample ---
    srt = sorted(items, key=lambda it: it["_p"]["dt"] if it["_p"] else dt.datetime.min.replace(tzinfo=dt.timezone.utc),
                 reverse=True)
    out["sample_newest"] = [dict(title=(it["title"] or "")[:110], link=it["link"], id=str(it["id"])[:80] if it["id"] else None,
                                 date_raw=str(it["date_raw"])[:40] if it["date_raw"] is not None else None)
                            for it in srt[:SAMPLE_N]]
    if len(srt) > SAMPLE_N:
        o = srt[-1]
        out["sample_oldest"] = dict(title=(o["title"] or "")[:110], date_raw=str(o["date_raw"])[:40] if o["date_raw"] is not None else None)
    return out


# --------------------------------------------------------------------------
# Разбор форматов
# --------------------------------------------------------------------------
def ln(tag):
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def el_text(el):
    return "".join(el.itertext()) if el is not None else ""


def parse_xml_bytes(b: bytes):
    """ET.fromstring с мягкими фолбэками (неопределённые HTML-сущности, мусор перед XML)."""
    b2 = b.lstrip(b"\xef\xbb\xbf \t\r\n")
    try:
        return ET.fromstring(b2)
    except ET.ParseError as e1:
        txt = b2.decode("utf-8", "replace")
        txt = re.sub(r"&(?!(?:amp|lt|gt|quot|apos|#\d+|#x[0-9a-fA-F]+);)[A-Za-z][A-Za-z0-9]*;",
                     lambda m: htmllib.unescape(m.group(0)) if htmllib.unescape(m.group(0)) != m.group(0) else "", txt)
        txt = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", txt)
        txt = re.sub(r"^<\?xml[^>]*\?>", "", txt.lstrip())
        try:
            return ET.fromstring(txt)
        except ET.ParseError:
            raise e1


DATE_ORDER_RSS = ("pubDate", "published", "date", "issued", "created", "updated", "modified")
DATE_ORDER_ATOM = ("published", "updated", "issued", "created", "modified", "pubDate", "date")


def first_child_text(el, names):
    for nm in names:
        for ch in el:
            if ln(ch.tag) == nm and (ch.text or len(ch)):
                return nm, el_text(ch).strip()
    return None, None


def parse_feed_xml(root):
    kind = ln(root.tag)
    meta, items = {}, []
    if kind == "rss":
        fmt = "rss" + (root.get("version") or "")
        ch = next((c for c in root if ln(c.tag) == "channel"), root)
        for c in ch:
            n = ln(c.tag)
            if n in ("title", "lastBuildDate", "ttl", "generator", "updated", "pubDate"):
                if n not in meta:
                    meta[n if n != "updated" else "channel_updated"] = el_text(c).strip()[:120]
        elems = [c for c in ch if ln(c.tag) == "item"]
        for e in elems:
            d = {}
            for c in e:
                d.setdefault(ln(c.tag), c)
            fld, raw = first_child_text(e, DATE_ORDER_RSS)
            link = el_text(d["link"]).strip() if "link" in d else None
            if not link and "link" in d and d["link"].get("href"):
                link = d["link"].get("href")
            guid = d.get("guid")
            gid = el_text(guid).strip() if guid is not None else None
            full_txt = strip_html(el_text(d["encoded"])) if "encoded" in d else ""
            desc_txt = strip_html(el_text(d["description"])) if "description" in d else ""
            body = max(len(full_txt), len(desc_txt)) if (full_txt or desc_txt or "description" in d or "encoded" in d) else None
            items.append(mk_item(id=gid or None, title=el_text(d["title"]) if "title" in d else None,
                                 link=link, date_raw=raw, date_field=fld, body_len=body,
                                 full=bool(full_txt)))
    elif kind == "feed":
        fmt = "atom"
        for c in root:
            n = ln(c.tag)
            if n in ("title", "updated", "generator") and n not in meta:
                meta[n if n != "updated" else "channel_updated"] = el_text(c).strip()[:120]
        for e in [c for c in root if ln(c.tag) == "entry"]:
            d = {}
            for c in e:
                d.setdefault(ln(c.tag), c)
            fld, raw = first_child_text(e, DATE_ORDER_ATOM)
            link = None
            for c in e:
                if ln(c.tag) == "link" and c.get("href"):
                    if c.get("rel") in (None, "alternate"):
                        link = c.get("href")
                        break
                    link = link or c.get("href")
            full_txt = strip_html(el_text(d["content"])) if "content" in d else ""
            sum_txt = strip_html(el_text(d["summary"])) if "summary" in d else ""
            body = max(len(full_txt), len(sum_txt)) if ("content" in d or "summary" in d) else None
            items.append(mk_item(id=el_text(d["id"]).strip() if "id" in d else None,
                                 title=el_text(d["title"]) if "title" in d else None,
                                 link=link, date_raw=raw, date_field=fld, body_len=body,
                                 full=bool(full_txt)))
    elif kind == "RDF":
        fmt = "rss1.0/rdf"
        for e in [c for c in root if ln(c.tag) == "item"]:
            d = {}
            for c in e:
                d.setdefault(ln(c.tag), c)
            fld, raw = first_child_text(e, DATE_ORDER_RSS)
            desc = strip_html(el_text(d["description"])) if "description" in d else ""
            items.append(mk_item(id=e.get("{http://www.w3.org/1999/02/22-rdf-syntax-ns#}about") or None,
                                 title=el_text(d["title"]) if "title" in d else None,
                                 link=el_text(d["link"]).strip() if "link" in d else None,
                                 date_raw=raw, date_field=fld, body_len=len(desc) if "description" in d else None,
                                 full=False))
    else:
        return None, meta, []
    return fmt, meta, items


def sniff(body: bytes, ctype: str):
    head = body[:4096].lstrip(b"\xef\xbb\xbf \t\r\n")
    hl = head.lower()
    if hl.startswith(b"<?xml") or hl.startswith(b"<rss") or hl.startswith(b"<feed") or hl.startswith(b"<rdf"):
        if re.search(rb"<(rss|feed|rdf:rdf|urlset|sitemapindex)\b", hl):
            return "xml"
    if hl.startswith(b"<!doctype html") or hl.startswith(b"<html") or b"<html" in hl[:1500] or b"<head" in hl[:1500]:
        return "html"
    if hl[:1] in (b"{", b"["):
        return "json"
    if b"<rss" in hl or b"<feed" in hl:
        return "xml"
    return "other"


AUTODISCOVER_RE = re.compile(
    r"<link[^>]+type=[\"']application/(?:rss|atom)\+xml[\"'][^>]*>", re.I)


def html_info(text: str, base_url: str):
    info = {}
    m = re.search(r"<title[^>]*>(.*?)</title>", text, re.S | re.I)
    if m:
        info["html_title"] = strip_html(m.group(1))[:120]
    links = []
    for tag in AUTODISCOVER_RE.findall(text):
        h = re.search(r"href=[\"']([^\"']+)", tag)
        if h:
            links.append(urljoin(base_url, htmllib.unescape(h.group(1))))
    if links:
        info["autodiscovered_feeds"] = links[:6]
    return info


BLOCK_MARKERS = [
    ("container_policy_github", re.compile(r"sessions are bound to their configured repositories|GitHub access to this repository is not enabled for this session", re.I)),
    ("vercel_challenge", re.compile(r"x-vercel-challenge|Vercel Security Checkpoint", re.I)),
    ("cloudflare_challenge", re.compile(r"Just a moment\.\.\.|cf-browser-verification|challenge-platform|Attention Required! \| Cloudflare|cf-chl-", re.I)),
    ("ddos_guard", re.compile(r"ddos-guard|DDoS-Guard", re.I)),
    ("akamai_denied", re.compile(r"Reference #\d+\.|Access Denied.*edgesuite", re.I | re.S)),
    ("datadome", re.compile(r"datadome", re.I)),
    ("qrator", re.compile(r"qrator", re.I)),
    ("reddit_block", re.compile(r"blocked by network security|whoa there, pardner|reddit.*block", re.I)),
    ("captcha", re.compile(r"captcha|are you a robot|verify you are human", re.I)),
]


def detect_block(resp: Resp, text: str | None):
    h = resp.headers
    srv = (h.get("server") or "").lower()
    kinds = []
    if h.get("cf-mitigated"):
        kinds.append("cloudflare_challenge")
    if (h.get("x-vercel-mitigated") or "").lower() == "challenge":
        kinds.append("vercel_challenge")
    if "showcaptcha" in (resp.url or "") or "smartcaptcha" in (resp.url or "").lower():
        kinds.append("yandex_smartcaptcha_redirect")
    if text is not None and (resp.status in (401, 403, 429, 451, 503) or len(text) < 6000):
        for nm, rx in BLOCK_MARKERS:
            if rx.search(text[:60000]):
                kinds.append(nm)
    if resp.status == 429:
        kinds.append("rate_limited_429")
    elif resp.status == 403:
        kinds.append("http_403_from_site" + (" (%s)" % srv if srv else ""))
    elif resp.status == 401:
        kinds.append("http_401_auth_required")
    elif resp.status == 451:
        kinds.append("http_451_legal")
    elif resp.status and resp.status >= 500:
        kinds.append("http_%d_server_error" % resp.status)
    return list(dict.fromkeys(kinds))


# --- специальные извлекатели ------------------------------------------------
def ex_sitemap(root, src):
    flt = src.get("url_filter")
    items = []
    for u in root:
        if ln(u.tag) != "url":
            continue
        loc = lm = None
        for c in u:
            if ln(c.tag) == "loc":
                loc = (c.text or "").strip()
            elif ln(c.tag) == "lastmod":
                lm = (c.text or "").strip()
        if loc and (not flt or flt in loc):
            items.append(mk_item(id=loc, link=loc, title=loc.rsplit("/", 1)[-1], date_raw=lm, date_field="lastmod"))
    return items


def ex_anthropic_html(text):
    items, seen = [], set()
    for m in re.finditer(r'\\?"publishedOn\\?":\\?"([^"\\]+)\\?",\\?"slug\\?":\{\\?"_type\\?":\\?"slug\\?",\\?"current\\?":\\?"([^"\\]+)', text):
        if m.group(2) in seen:
            continue
        seen.add(m.group(2))
        tm = re.search(r'\\?"title\\?":\\?"([^"\\]{3,160})', text[m.end():m.end() + 1500])
        items.append(mk_item(id=m.group(2), link="https://www.anthropic.com/news/" + m.group(2),
                             title=tm.group(1) if tm else m.group(2), date_raw=m.group(1),
                             date_field="publishedOn"))
    return items


def ex_html_generic(text):
    """Метки времени, встроенные в HTML: <time datetime=..> и ISO-строки в JSON/скриптах.
    Слабый признак (нет привязки к заголовкам) -- только оценка «живости» страницы."""
    raws = re.findall(r"<time[^>]*datetime=[\"']([^\"']+)", text, re.I)
    raws += re.findall(r"[\"'](20\d\d-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?(?:Z|[+-]\d\d:?\d\d)?)[\"']", text)
    raws += re.findall(r"\\\"(20\d\d-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?(?:Z|[+-]\d\d:?\d\d)?)\\\"", text)
    seen, items = set(), []
    for r in raws:
        if r in seen:
            continue
        seen.add(r)
        items.append(mk_item(date_raw=r, date_field="embedded"))
    return items


def ex_telegram(text):
    items = []
    blocks = re.split(r'(?=<div class="tgme_widget_message_wrap)', text)
    for b in blocks[1:]:
        post = re.search(r'data-post="([^"]+)"', b)
        tm = re.search(r'<time[^>]*datetime="([^"]+)"', b)
        body = re.search(r'<div class="tgme_widget_message_text[^>]*>(.*?)</div>', b, re.S)
        views = re.search(r'tgme_widget_message_views">([^<]+)<', b)
        t = strip_html(body.group(1)) if body else ""
        it = mk_item(id=post.group(1) if post else None,
                     title=t[:110] or ("[media/no text]" if post else None),
                     link=("https://t.me/" + post.group(1)) if post else None,
                     date_raw=tm.group(1) if tm else None, date_field="time@datetime",
                     body_len=len(t), full=bool(t))
        it["views"] = views.group(1) if views else None
        items.append(it)
    return items


def ex_hn_algolia(js):
    return [mk_item(id=h.get("objectID"), title=h.get("title") or h.get("story_title"),
                    link=h.get("url"), date_raw=h.get("created_at"), date_field="created_at",
                    body_len=len(h.get("story_text") or ""), full=False)
            for h in js.get("hits", [])]


def ex_reddit_json(js):
    ch = (js.get("data") or {}).get("children") or []
    out = []
    for c in ch:
        d = c.get("data", {})
        out.append(mk_item(id=d.get("name") or d.get("id"), title=d.get("title"),
                           link="https://www.reddit.com" + d.get("permalink", ""),
                           date_raw=d.get("created_utc"), date_field="created_utc",
                           body_len=len(d.get("selftext") or ""), full=bool(d.get("selftext"))))
    return out


def ex_hf_papers(js):
    out = []
    for e in js if isinstance(js, list) else []:
        p = e.get("paper") or {}
        out.append(mk_item(id=p.get("id"), title=e.get("title") or p.get("title"),
                           link="https://huggingface.co/papers/%s" % p.get("id"),
                           date_raw=e.get("publishedAt") or p.get("publishedAt"), date_field="publishedAt",
                           body_len=len(e.get("summary") or p.get("summary") or ""), full=False))
    return out


def ex_hf_models(js):
    return [mk_item(id=e.get("id") or e.get("modelId"), title=e.get("id"),
                    link="https://huggingface.co/%s" % e.get("id"),
                    date_raw=e.get("createdAt"), date_field="createdAt")
            for e in (js if isinstance(js, list) else [])]


def ex_bsky(js):
    out = []
    posts = js.get("posts") or [f.get("post") for f in js.get("feed", []) if f.get("post")]
    for p in posts:
        rec = p.get("record", {})
        out.append(mk_item(id=p.get("uri"), title=(rec.get("text") or "")[:110],
                           link=p.get("uri"), date_raw=rec.get("createdAt") or p.get("indexedAt"),
                           date_field="record.createdAt", body_len=len(rec.get("text") or ""), full=True))
    return out


def ex_mastodon(js):
    out = []
    for s in js if isinstance(js, list) else []:
        t = strip_html(s.get("content") or "")
        out.append(mk_item(id=s.get("id"), title=t[:110], link=s.get("url"),
                           date_raw=s.get("created_at"), date_field="created_at",
                           body_len=len(t), full=True))
    return out


def ex_npm(js):
    tm = js.get("time") or {}
    out = []
    for ver, ts in tm.items():
        if ver in ("created", "modified"):
            continue
        out.append(mk_item(id=ver, title=ver, link="https://www.npmjs.com/package/%s/v/%s" % (js.get("name"), ver),
                           date_raw=ts, date_field="time[version]"))
    return out


def ex_html_textdates(text):
    """Даты вида «September 30, 2026» в видимом тексте страницы (только дата, без времени).
    Берём первые 60 в порядке документа (страницы release-notes идут от новых к старым)."""
    plain = htmllib.unescape(re.sub(r"<[^>]+>", " ", re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", text, flags=re.S | re.I)))
    out, seen = [], set()
    for m in TEXTDATE_RE.finditer(plain):
        raw = "%s %s, %s" % (m.group(1), m.group(2), m.group(3))
        out.append(mk_item(date_raw=raw, date_field="text"))
        if len(out) >= 60:
            break
    return out


def access_class(rec):
    """Сводная классификация доступности (для таблицы в отчёте)."""
    ec, st = rec.get("error_class"), rec.get("http_status")
    blk = " ".join(rec.get("block") or [])
    if ec == "proxy_policy_denied":
        return "container_policy"
    if ec:
        return "net_error:" + ec
    if "container_policy_github" in blk:
        return "container_policy"
    if st in (404, 410):
        return "not_found_or_moved"
    if st in (401, 422):
        return "auth_required"
    if st == 451:
        return "site_block_451"
    if st == 429 or "vercel_challenge" in blk:
        return "site_block_429_or_challenge"
    if st == 403 or "cloudflare_challenge" in blk or "yandex_smartcaptcha_redirect" in blk:
        return "site_block_403_or_captcha"
    if st and st >= 400:
        return "http_%d" % st
    if rec.get("n_items"):
        return "ok"
    if st and st < 400:
        return "200_but_no_items"
    return "unknown"


# --------------------------------------------------------------------------
# Проверка одного источника
# --------------------------------------------------------------------------
def probe(src: dict) -> dict:
    kind = src["kind"]
    f = Fetcher(nav=kind in HTML_KINDS)
    rec = dict(id=src["id"], group=src["group"], name=src["name"], url=src["url"], kind=kind)
    t_start = time.monotonic()
    r = f.get(src["url"])
    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)   # возраст считаем от момента ответа
    rec.update(probed_at_utc=now.isoformat(), http_status=r.status,
               final_url=r.url if r.url != src["url"] else None,
               redirects=[list(h) for h in r.history] or None,
               elapsed_s=r.elapsed, bytes=len(r.body), truncated=r.truncated or None)
    if f.retried:
        rec["retried"] = f.retried
        rec["first_attempt_error"] = r.first_error
    flags = []
    if r.error_class:
        rec.update(error=r.error, error_class=r.error_class)
        ps = proxy_status()
        if ps is not None:
            host = urlparse(src["url"]).hostname or ""
            rf = [x for x in ps.get("recentRelayFailures", []) if host in json.dumps(x)]
            rec["proxy_status_relevant"] = rf or None
        rec["flags"] = ["net_error:" + r.error_class]
        rec["auto_ok"] = False
        rec["requests_made"] = f.requests_made
        rec["access_class"] = access_class(rec)
        return rec
    if r.error:
        rec["error"] = r.error
    hd = {k: v for k, v in r.headers.items() if k in KEEP_HEADERS}
    rec["content_type"] = r.headers.get("content-type")
    rec["headers"] = hd

    body = r.body
    sn = sniff(body, r.headers.get("content-type", ""))
    text = None
    if sn in ("html", "json", "other"):
        enc = "utf-8"
        m = re.search(r"charset=[\"']?([\w-]+)", r.headers.get("content-type", ""), re.I)
        if m:
            enc = m.group(1)
        try:
            text = body.decode(enc, "replace")
        except LookupError:
            text = body.decode("utf-8", "replace")

    items, fmt, meta = [], None, {}
    extra = {}

    if r.status and r.status >= 400:
        rec["block"] = detect_block(r, text if text is not None else body[:20000].decode("utf-8", "replace"))
        rec["format"] = sn
        rec["body_head"] = (text or body[:300].decode("utf-8", "replace"))[:200].replace("\n", " ")
        rec["flags"] = ["http_%d" % r.status] + rec["block"]
        rec["auto_ok"] = False
        if r.headers.get("retry-after"):
            rec["retry_after"] = r.headers["retry-after"]
        rec["requests_made"] = f.requests_made
        rec["access_class"] = access_class(rec)
        return rec

    # ---- разбор по содержимому ----
    try:
        if sn == "xml":
            root = parse_xml_bytes(body)
            rn = ln(root.tag)
            if rn == "urlset" or (kind == "sitemap" and rn != "sitemapindex"):
                fmt = "sitemap"
                items = ex_sitemap(root, src)
            elif rn == "sitemapindex":
                fmt = "sitemapindex"
            else:
                fmt, meta, items = parse_feed_xml(root)
                if fmt is None:
                    fmt = "xml:" + rn
        elif sn == "json":
            js = json.loads(body.decode("utf-8", "replace"))
            fmt = "json"
            if kind == "hn_algolia":
                items = ex_hn_algolia(js)
            elif kind == "reddit_json":
                items = ex_reddit_json(js)
            elif kind == "hf_papers":
                items = ex_hf_papers(js)
            elif kind == "hf_models":
                items = ex_hf_models(js)
            elif kind == "bsky":
                items = ex_bsky(js)
            elif kind == "mastodon":
                items = ex_mastodon(js)
            elif kind == "npm":
                items = ex_npm(js)
            elif kind == "hn_firebase":
                ids = js[:12] if isinstance(js, list) else []
                extra["newstories_count"] = len(js) if isinstance(js, list) else None
                for i in ids:
                    ir = f.get("https://hacker-news.firebaseio.com/v0/item/%s.json" % i)
                    try:
                        d = json.loads(ir.body.decode("utf-8", "replace")) if ir.status == 200 else None
                    except ValueError:
                        d = None
                    if d:
                        items.append(mk_item(id=d.get("id"), title=d.get("title"),
                                             link=d.get("url") or "https://news.ycombinator.com/item?id=%s" % i,
                                             date_raw=d.get("time"), date_field="time",
                                             body_len=len(strip_html(d.get("text") or "")), full=False))
            else:
                extra["json_top"] = (list(js.keys())[:12] if isinstance(js, dict) else "list[%d]" % len(js))
        elif sn == "html":
            fmt = "html"
            rec.update(html_info(text, r.url))
            if kind == "anthropic_html":
                items = ex_anthropic_html(text)
                fmt = "html+embedded_json"
            elif kind == "telegram":
                items = ex_telegram(text)
                fmt = "html/telegram-preview"
                extra["telegram_messages"] = len(items)
            elif kind == "html":
                items = ex_html_generic(text)
                if items:
                    extra["dates_source"] = "<time>/ISO в разметке"
                else:
                    items = ex_html_textdates(text)
                    if items:
                        extra["dates_source"] = "даты текстом «Month D, YYYY» (первые 60 в порядке документа)"
                fmt = "html (даты вытащены из разметки)" if items else "html"
            else:
                flags.append("html_instead_of_feed")
        else:
            fmt = "other"
            rec["body_head"] = body[:200].decode("utf-8", "replace").replace("\n", " ")
    except Exception as e:  # noqa: BLE001
        rec["parse_error"] = "%s: %s" % (type(e).__name__, str(e)[:200])
        flags.append("parse_error")
        rec["body_head"] = body[:200].decode("utf-8", "replace").replace("\n", " ")

    rec["format"] = fmt
    if meta:
        rec["feed_meta"] = meta
    rec.update(extra)
    if sn in ("html", "other") and text is not None:
        blk = detect_block(r, text)
        if blk:
            rec["block"] = blk
            flags += blk
        if not items:
            rec.setdefault("body_head", text[:200].replace("\n", " "))
    if not body and r.status and r.status < 400:
        flags.append("empty_body_with_http_%d" % r.status)
    stats = analyze_items(items, now)
    rec.update(stats)
    if src["id"] in HN_CROSSCHECK:
        rec["_xcheck_items"] = [(it["link"], it["_p"]["dt"]) for it in items if it.get("link") and it.get("_p")]
    # ---- флаги ----
    if fmt and fmt.startswith(("rss", "atom", "rss1")) and not items:
        flags.append("empty_feed")
    st = stats
    if st.get("newest_age_min") is not None:
        a = st["newest_age_min"]
        if a < -10:
            flags.append("newest_in_future")
        elif a > 14 * 24 * 60:
            flags.append("stale_>14d")
        elif a > 3 * 24 * 60:
            flags.append("stale_>3d")
    if st.get("n_future_gt10min"):
        flags.append("future_dates")
    p = st.get("precision")
    if st.get("time_class") in ("midnight_stub", "constant_time", "hour_rounded", "date_only"):
        flags.append("time_" + st["time_class"])
    if p and p["share_no_tz"] and p["share_no_tz"] >= 0.5:
        flags.append("tz_missing")
    if st.get("n_items") and (st.get("stable_key_coverage") or 0) < 0.9 and kind not in ("html", "sitemap"):
        flags.append("no_stable_key")
    elif st.get("n_items") and (st.get("id_coverage") or 0) < 0.9 and kind not in ("html", "sitemap"):
        flags.append("no_guid_link_only")
    if st.get("text_mode") == "title_only" and st.get("n_items") and kind not in ("html", "sitemap", "npm", "anthropic_html"):
        flags.append("title_only")
    if st.get("n_items") and st.get("n_with_date", 0) < 0.8 * st["n_items"] and kind != "html":
        flags.append("dates_missing")
    if st.get("n_items", 0) and st["n_items"] <= 12 and kind not in ("html", "hn_firebase"):
        flags.append("short_window_<=12")

    # ---- conditional GET ----
    etag, lm = hd.get("etag"), hd.get("last-modified")
    if kind == "feed" and items and (etag or lm):
        ch = {}
        if etag:
            ch["If-None-Match"] = etag
        if lm:
            ch["If-Modified-Since"] = lm
        cr = f.get(src["url"], headers=ch, max_bytes=20000)
        rec["conditional_get"] = dict(sent=sorted(ch), status=cr.status,
                                      supports_304=(cr.status == 304))
    elif kind == "feed" and items:
        rec["conditional_get"] = dict(sent=[], status=None, supports_304=False,
                                      note="нет ETag/Last-Modified в ответе")

    rec["flags"] = flags
    rec["auto_ok"] = bool(items) and not ({"parse_error", "html_instead_of_feed", "empty_feed"} & set(flags))
    rec["requests_made"] = f.requests_made
    rec["total_time_s"] = round(time.monotonic() - t_start, 1)
    rec["access_class"] = access_class(rec)
    return rec


# --------------------------------------------------------------------------
# Кросс-проверка времени ленты по Hacker News
# --------------------------------------------------------------------------
def _norm_url(u):
    u = (u or "").split("#")[0].split("?")[0].rstrip("/")
    u = re.sub(r"^http://", "https://", u)
    return u.replace("://www.", "://")


def _q(xs, ps=(0.1, 0.25, 0.5, 0.75, 0.9)):
    xs = sorted(xs)
    return [round(xs[min(len(xs) - 1, int(len(xs) * p))], 2) for p in ps] if xs else None


def hn_crosscheck(feed_id, items, domain, pages=5, recent_days=150):
    """Сравнивает время элемента ленты с самым ранним постом этого URL на Hacker News (Algolia).
    HN-время -- НЕ истина, а верхняя оценка момента публикации (пост не раньше самой публикации,
    но обычно через минуты-часы). Поэтому смотрим на СИСТЕМАТИЧЕСКИЙ сдвиг и его моду,
    а не на отдельные значения. Вторая гипотеза: «время в ленте -- локальное Pacific, ошибочно
    помеченное GMT» -- проверяется переинтерпретацией wall-clock как America/Los_Angeles."""
    try:
        from zoneinfo import ZoneInfo
        PT = ZoneInfo("America/Los_Angeles")
    except Exception:  # noqa: BLE001
        PT = None
    f = Fetcher()
    feed = {}
    for link, t in items:
        feed[_norm_url(link)] = t
    hits = []
    n_req = 0
    for page in range(pages):
        u = ("https://hn.algolia.com/api/v1/search_by_date?query=%s&restrictSearchableAttributes=url"
             "&tags=story&hitsPerPage=100&page=%d" % (domain, page))
        r = f.get(u)
        n_req += 1
        if r.status != 200:
            return dict(feed=feed_id, domain=domain, error="algolia status %s" % r.status)
        js = json.loads(r.body.decode("utf-8", "replace"))
        hits += js.get("hits", [])
        if page + 1 >= js.get("nbPages", 1):
            break
    first = {}
    for h in hits:
        u = _norm_url(h.get("url"))
        if u in feed and h.get("created_at"):
            t = dt.datetime.fromisoformat(h["created_at"].replace("Z", "+00:00"))
            if u not in first or t < first[u]:
                first[u] = t
    cut = NOW - dt.timedelta(days=recent_days)
    rows = []
    for u, t in first.items():
        ft = feed[u]
        if ft < cut:
            continue
        mid = (ft.hour, ft.minute, ft.second) == (0, 0, 0)
        d_utc = (t - ft).total_seconds() / 3600
        d_pt = None
        if PT:
            ft_pt = ft.replace(tzinfo=None).replace(tzinfo=PT).astimezone(dt.timezone.utc)
            d_pt = (t - ft_pt).total_seconds() / 3600
        rows.append((mid, d_utc, d_pt, u))
    out = dict(feed=feed_id, domain=domain, hn_hits_scanned=len(hits), feed_urls=len(feed),
               matched_total=len(first), matched_recent=len(rows), recent_days=recent_days,
               delta_definition="HN_first_submission - feed_time (часы); >0 = HN позже ленты")
    for label, sel in (("non_midnight", [r for r in rows if not r[0]]), ("midnight_00_00_utc", [r for r in rows if r[0]])):
        if not sel:
            out[label] = dict(n=0)
            continue
        d1 = [r[1] for r in sel]
        blk = dict(n=len(sel), delta_label_as_utc_q10_25_50_75_90=_q(d1),
                   share_delta_between_6_5_and_8_5h=round(sum(1 for d in d1 if 6.5 <= d <= 8.5) / len(d1), 2),
                   share_delta_negative=round(sum(1 for d in d1 if d < -0.5) / len(d1), 2))
        if PT:
            d2 = [r[2] for r in sel]
            blk.update(delta_if_wallclock_is_pacific_q10_25_50_75_90=_q(d2),
                       share_pacific_delta_between_minus0_5_and_3h=round(sum(1 for d in d2 if -0.5 <= d <= 3) / len(d2), 2))
        out[label] = blk
    out["examples_newest"] = [dict(url=r[3][-70:], feed_time_utc_label=feed[r[3]].strftime("%Y-%m-%d %H:%M"),
                                   hn_first_utc=first[r[3]].strftime("%Y-%m-%d %H:%M"), delta_h=round(r[1], 1))
                              for r in sorted(rows, key=lambda r: feed[r[3]], reverse=True)[:8]]
    out["requests_made"] = f.requests_made
    return out


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------
# --------------------------------------------------------------------------
# Необязательный эксперимент: задержка появления новых элементов (--latency MIN)
# --------------------------------------------------------------------------
def parse_items(src, r):
    """Быстрый разбор ответа в список элементов (для повторного опроса)."""
    kind = src["kind"]
    sn = sniff(r.body, r.headers.get("content-type", ""))
    if sn == "xml":
        root = parse_xml_bytes(r.body)
        fmt, _meta, items = parse_feed_xml(root)
        return items
    text = r.body.decode("utf-8", "replace")
    if sn == "html" and kind == "telegram":
        return ex_telegram(text)
    if sn == "json":
        js = json.loads(text)
        return {"hn_algolia": ex_hn_algolia, "mastodon": ex_mastodon, "bsky": ex_bsky,
                "hf_models": ex_hf_models}[kind](js)
    return []


def item_key(it):
    return str(it["id"] or it["link"] or it["title"])


def latency_experiment(ids, minutes, interval):
    srcs = [s for s in SOURCES if s["id"] in ids]
    t_end = time.time() + minutes * 60
    st = {s["id"]: dict(seen=None, new=[], polls=0, n_304=0, errors=0, last_poll=None, etag=None, lm=None)
          for s in srcs}
    groups = collections.OrderedDict()
    for s in srcs:
        groups.setdefault(host_key(s["url"]), []).append(s)

    def loop(group):
        fetchers = {s["id"]: Fetcher(nav=s["kind"] in HTML_KINDS) for s in group}
        while time.time() < t_end:
            round_start = time.time()
            for s in group:
                S_ = st[s["id"]]
                hdr = {}
                if S_["etag"]:
                    hdr["If-None-Match"] = S_["etag"]
                if S_["lm"]:
                    hdr["If-Modified-Since"] = S_["lm"]
                r = fetchers[s["id"]].get(s["url"], headers=hdr)
                t_poll = dt.datetime.now(dt.timezone.utc)
                S_["polls"] += 1
                if r.status == 304:
                    S_["n_304"] += 1
                    S_["last_poll"] = t_poll
                    continue
                if r.status != 200:
                    S_["errors"] += 1
                    continue
                S_["etag"] = r.headers.get("etag")
                S_["lm"] = r.headers.get("last-modified")
                try:
                    items = parse_items(s, r)
                except Exception:  # noqa: BLE001
                    S_["errors"] += 1
                    continue
                keys = {item_key(it) for it in items}
                if not keys:                    # пустой/битый разбор -- не считаем базовой линией
                    S_["errors"] += 1
                    continue
                if S_["seen"] is None:          # первый успешный опрос -- только базовая линия
                    S_["seen"] = keys
                else:
                    for it in items:
                        k = item_key(it)
                        if k in S_["seen"]:
                            continue
                        p = parse_date(it["date_raw"]) if it["date_raw"] is not None else None
                        S_["new"].append(dict(title=(it["title"] or "")[:60], pub=p["dt"] if p else None,
                                              seen_at=t_poll, prev_poll=S_["last_poll"]))
                    S_["seen"] |= keys
                S_["last_poll"] = t_poll
            rest = interval - (time.time() - round_start)
            if time.time() + max(rest, 0) >= t_end:
                break                      # следующий раунд уже не уложился бы в окно
            if rest > 0:
                time.sleep(rest)

    with cf.ThreadPoolExecutor(max_workers=len(groups) or 1) as ex:
        list(ex.map(loop, groups.values()))

    out = {}
    for s in srcs:
        S_ = st[s["id"]]
        up = [(n["seen_at"] - n["pub"]).total_seconds() for n in S_["new"] if n["pub"]]
        lo = [(n["prev_poll"] - n["pub"]).total_seconds() for n in S_["new"] if n["pub"] and n["prev_poll"]]
        fresh = [x for x in up if -60 <= x <= 3600]
        out[s["id"]] = dict(
            polls=S_["polls"], not_modified_304=S_["n_304"], errors=S_["errors"], new_items=len(S_["new"]),
            new_fresh_le_1h=len(fresh), new_late_gt_1h=sum(1 for x in up if x > 3600),
            lag_upper_s_fresh_q25_50_75=_q(fresh, (0.25, 0.5, 0.75)) if fresh else None,
            lag_upper_s_q25_50_75=_q(up, (0.25, 0.5, 0.75)) if up else None,
            lag_upper_s_min_max=[round(min(up)), round(max(up))] if up else None,
            lag_lower_s_median=round(statistics.median(lo)) if lo else None,
            n_negative_lag=sum(1 for x in up if x < -60),
            examples=[dict(title=n["title"], pub=n["pub"].strftime("%H:%M:%S") if n["pub"] else None,
                           seen=n["seen_at"].strftime("%H:%M:%S")) for n in S_["new"][:4]])
    return dict(minutes=minutes, interval_s=interval, ids=ids,
                definition=("lag_upper = момент нашего опроса, на котором элемент впервые увидели, минус время элемента "
                            "в ленте (верхняя оценка задержки лента/кэш + шаг опроса); lag_lower = то же для предыдущего "
                            "опроса (нижняя оценка). fresh = новые элементы с lag<=1 ч; late = элементы, появившиеся в ленте позже чем "
                            "через час после своей даты (лента не хронологична / источник индексирует с задержкой). "
                            "Осмысленно только при секундной точности времени и корректном поясе."),
                results=out)



def fmt_age(m):
    if m is None:
        return "-"
    if m < 0:
        return "FUT%.0fm" % -m
    if m < 120:
        return "%.0fm" % m
    if m < 48 * 60:
        return "%.1fh" % (m / 60)
    return "%.1fd" % (m / 1440)


def pct(x):
    return "-" if x is None else "%d%%" % round(x * 100)


def print_table(recs):
    hdr = "%-27s %-5s %-13s %5s %7s %-16s %5s %5s %5s  %s"
    print(hdr % ("id", "http", "format", "n", "age", "time-class", "00:00", ":00:00", "sec=0", "access / flags"))
    print("-" * 140)
    for r in recs:
        p = r.get("precision") or {}
        st = r.get("http_status") or r.get("error_class") or "-"
        acc = r.get("access_class", "")
        fl = ",".join(x for x in (r.get("flags") or []) if not x.startswith(("http_4", "http_5")))
        print(hdr % (r["id"][:27], str(st)[:5], (r.get("format") or "-")[:13], r.get("n_items", "-"),
                     fmt_age(r.get("newest_age_min")), r.get("time_class", "-"),
                     pct(max(p.get("share_midnight_raw") or 0, p.get("share_midnight_utc") or 0)) if p else "-",
                     pct(max(p.get("share_round_hour_raw") or 0, p.get("share_round_hour_utc") or 0)) if p else "-",
                     pct(p.get("share_zero_seconds_utc")) if p else "-",
                     (acc + (" | " + fl if fl else ""))[:70]))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", default=str(DEFAULT_OUT), help="куда писать JSON (относительно корня репозитория)")
    ap.add_argument("--only", help="id источников через запятую")
    ap.add_argument("--group", help="группа: lab, code, agg, media_en, media_ru, telegram")
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--no-crosscheck", action="store_true", help="не делать кросс-проверку времени по HN")
    ap.add_argument("--latency", type=float, default=0, metavar="MIN",
                    help="после основного прогона MIN минут опрашивать быстрые ленты и мерить задержку появления новых элементов")
    ap.add_argument("--latency-interval", type=float, default=40, help="шаг опроса, сек (по умолчанию 40)")
    a = ap.parse_args(argv)

    srcs = SOURCES
    if a.only:
        want = set(a.only.split(","))
        srcs = [s for s in srcs if s["id"] in want]
    if a.group:
        srcs = [s for s in srcs if s["group"] == a.group]
    if a.list:
        for s in srcs:
            print("%-30s %-9s %s" % (s["id"], s["group"], s["url"]))
        print(len(srcs), "sources")
        return 0

    ps0 = proxy_status()
    # группируем по домену: внутри домена последовательно (вежливость), между доменами параллельно
    by_host = collections.OrderedDict()
    for s in srcs:
        by_host.setdefault(host_key(s["url"]), []).append(s)

    def run_group(group):
        res = []
        for s in group:
            try:
                res.append(probe(s))
            except Exception as e:  # noqa: BLE001
                res.append(dict(id=s["id"], group=s["group"], name=s["name"], url=s["url"],
                                kind=s["kind"], error="probe crashed: %s: %s" % (type(e).__name__, e),
                                error_class="probe_crash", flags=["probe_crash"], auto_ok=False,
                                access_class="probe_crash"))
        return res

    t0 = time.time()
    out = {}
    with cf.ThreadPoolExecutor(max_workers=a.workers) as ex:
        futs = [ex.submit(run_group, g) for g in by_host.values()]
        for fu in cf.as_completed(futs):
            for rec in fu.result():
                out[rec["id"]] = rec
    recs = [out[s["id"]] for s in srcs]

    # кросс-проверка времени по HN (последовательно; Algolia -- вежливо, 1 запрос/сек)
    crosschecks = {}
    if not a.no_crosscheck:
        for rec in recs:
            xi = rec.pop("_xcheck_items", None)
            if xi and rec["id"] in HN_CROSSCHECK:
                try:
                    crosschecks[rec["id"]] = hn_crosscheck(rec["id"], xi, HN_CROSSCHECK[rec["id"]])
                except Exception as e:  # noqa: BLE001
                    crosschecks[rec["id"]] = dict(feed=rec["id"], error="%s: %s" % (type(e).__name__, e))
    for rec in recs:
        rec.pop("_xcheck_items", None)

    lat_res = None
    if a.latency and a.latency > 0:
        ids = [i for i in LATENCY_IDS if i in {s["id"] for s in srcs}]
        print("latency experiment: %d sources, %.1f min, every %.0f s ..." % (len(ids), a.latency, a.latency_interval), flush=True)
        lat_res = latency_experiment(ids, a.latency, a.latency_interval)

    ps1 = proxy_status()
    doc = {
        "meta": {
            "generated_at_utc": NOW.isoformat(),
            "duration_s": round(time.time() - t0, 1),
            "script": "tools/feeds_probe.py",
            "python": platform.python_version(),
            "requests": requests.__version__,
            "user_agent": UA,
            "timeout_s": TIMEOUT,
            "min_interval_per_domain_s": MIN_INTERVAL,
            "host_interval_overrides_s": HOST_INTERVAL,
            "tls_verify": True,
            "n_sources": len(recs),
            "n_by_group": dict(collections.Counter(r["group"] for r in recs)),
            "n_by_access_class": dict(collections.Counter(r.get("access_class") for r in recs)),
            "note": ("Снимок «сейчас». Задержка событие->лента не измеряется. "
                     "time_class (по 30 самым свежим элементам): date_only / midnight_stub / constant_time (одно время суток у >=50%: "
                     "расписание публикаций ИЛИ заглушка -- сверять с HN) / hour_rounded / minute_precision / second_precision. "
                     "Доли в precision: share_midnight_* = 00:00:00, share_round_hour_* = минуты и секунды нулевые "
                     "(включает 00:00:00), share_zero_seconds_utc = секунды нулевые."),
            "proxy_relay_failures_before": (ps0 or {}).get("recentRelayFailures") if ps0 else None,
            "proxy_relay_failures_after": (ps1 or {}).get("recentRelayFailures") if ps1 else None,
        },
        "crosschecks_vs_hn": crosschecks,
        "latency_experiment": lat_res,
        "sources": recs,
    }
    outp = Path(a.out)
    if not outp.is_absolute():
        outp = ROOT / outp
    outp.parent.mkdir(parents=True, exist_ok=True)
    outp.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    print_table(recs)
    for k, v in crosschecks.items():
        print("\ncrosscheck vs HN: %s -> matched_recent=%s non_midnight=%s midnight=%s" % (
            k, v.get("matched_recent"), json.dumps(v.get("non_midnight"), ensure_ascii=False)[:230],
            json.dumps(v.get("midnight_00_00_utc"), ensure_ascii=False)[:160]))
    if lat_res:
        print("\nlatency (сек; upper = увидели - время в ленте):")
        for k, v in lat_res["results"].items():
            print("  %-18s polls=%-3d 304=%-3d err=%-2d new=%-3d (fresh<=1h %d, late>1h %d) fresh lag_upper q25/50/75=%s" % (
                k, v["polls"], v["not_modified_304"], v["errors"], v["new_items"], v["new_fresh_le_1h"],
                v["new_late_gt_1h"], v["lag_upper_s_fresh_q25_50_75"]))
    try:
        shown = os.path.relpath(outp, ROOT)
    except ValueError:
        shown = str(outp)
    print("\nwritten: %s  (%d sources, %.0fs, now=%s)" % (shown, len(recs), time.time() - t0, NOW.isoformat()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
