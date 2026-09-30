import requests
from concurrent.futures import ThreadPoolExecutor
from bs4 import BeautifulSoup

S = requests.Session()
S.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"})

CAND = """
anthropic discover discovertech technews TechNews tech_news technews_daily
theanthropic claude_news claudeai_news openai_news chatgpt_news gpt_news_en
aichat aichatnews ainews_en2 ai_for_people aiforfuture futureofai
theaipaper AIPapers research_papers paperswithcode researchfeed
AI_Engineering MLE mleng MLOps mlops eng_ai ai_engineer
TechNewsToday DailyTechNews TechBrief techbrief DailyBrief
AInewsletter AIletter theletter Briefings dailybrief
thenextweb TNW ArsTechnica2 theverge2 VentureBeat Engadget2
WIRED2 TechRadar2 CNET ZDNET2 GSMarena AndroidAuthority
9to5Google 9to5Mac AppleInsider AndroidCentral PCMag
crypto_a news_crypto web3news defi_news
gitnews gitea_ changelog release_notes releasenotes
DevCircle devcircle_ fullstack fullstackdev webdev_
AI_Agent ai_agents agentic AIAgents2 langchain llamaindex
n8n_ Zapier_ automation_ noCode_ nocode_
opensource_ OpenSource opensource_daily
quantfinance_ ai_trading algo_trading
""".split()

def check(c):
    try:
        r = S.get(f"https://t.me/s/{c}", timeout=20)
        s = BeautifulSoup(r.text, "html.parser")
        cn = s.select_one(".tgme_channel_info_header_title span")
        sub = s.select_one(".tgme_channel_info_counter .counter_value")
        dts = [t.get("datetime") for t in s.select("time[datetime]")]
        if not cn or not dts:
            return None
        newest = max(dts)
        if not newest.startswith("2026-09-2"):
            return None
        n = len(s.select("div.tgme_widget_message[data-post]"))
        return (c, cn.get_text(strip=True)[:40], sub.get_text(strip=True) if sub else "?", n, newest[:10])
    except Exception:
        return None

with ThreadPoolExecutor(max_workers=8) as ex:
    for res in ex.map(check, dict.fromkeys(CAND)):
        if res:
            print("OK  %-26s %-42s %8s posts=%-3d newest=%s" % res, flush=True)
