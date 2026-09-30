import requests, sys
from concurrent.futures import ThreadPoolExecutor
from bs4 import BeautifulSoup

S = requests.Session()
S.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"})

CAND = """
tldrtech tldrnews tldr tldrsignals TheSequenceAI thesquairetech
aipost artificial_intelligence_neural hiaimediaen TechDaily TechNewsPlus
AIAgentNews aiagentnews ainews AInewsnow AINewsNow aitoday AI_today
ArtificialIntelligenceNews AINewsFeed theaigrid TheAIGrid ai_industry
LatentSpace latent_space exponent TheGradient deeplearning_ai
machinelearningresearchnews machinelearning researchnews ml_news
levelsio simonwlevelsio bskytech swyx gdb sama karpathy ylecun AndrewYNg
HuggingFace huggingface_ai anthropic Claude claudeai OpenAI openai
GoogleDeepMind deepmind GoogleAI MetaAI metaai MicrosoftAI AppleAI
perplexity_ai PerplexityAI cursor_ai CursorAI WindsurfAI ReplitAI
Kimi_Moonshot MoonshotAI deepseek_ai DeepSeekAI GrokAInews xAI zai_org
QwenAI Alibaba_Qwen MistralAI cohere NvidiaAI NVIDIAAI StabilityAI
RunwayML LumaLabslabs ElevenLabsEleven SunoAI MidjourneyMJ
DevOpsNews OpenSourceNews StackOverflow GitHub github_trending
Techmeme tech2 theverge verge TechCrunch TechRadar ZDNet Engadget
WIRED ArsTechnica TheRegister MITTechReview IEEE Spectrum
AInews_en technews_en newsbyte AIbyte NewsByte
nextjs reactjs nodejs pythonlang rustlang golang
startup_tech techstartup venturecapital YCombinator
cybersecurity c-sec infosec malware bleepingcomputer TheHackerNews
privacy_tech netsec securitynews
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
        if not newest.startswith("2026-09"):
            return None
        n = len(s.select("div.tgme_widget_message[data-post]"))
        return (c, cn.get_text(strip=True)[:40], sub.get_text(strip=True) if sub else "?", n, newest[:10])
    except Exception:
        return None

with ThreadPoolExecutor(max_workers=8) as ex:
    for res in ex.map(check, dict.fromkeys(CAND)):
        if res:
            print("OK  %-26s %-42s %8s posts=%-3d newest=%s" % res, flush=True)
