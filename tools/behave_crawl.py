"""Сбор поведенческих данных: views + РЕАКЦИИ (по типам) по каждому посту.

Telegram в публичном превью отдаёт:
  .tgme_widget_message_views      — просмотры
  .tgme_widget_message_reactions  — блок реакций
      первый .tgme_reaction       — ВСЕГО реакций
      остальные                   — "эмодзи <число>" (либо только <число>,
                                   если эмодзи отрисован через CSS)
Пагинация: ?before=<post_id>

Запуск: python tools/behave_crawl.py
Выход: data/reactions.json
"""
import json, re, sys, time, random
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import requests
from bs4 import BeautifulSoup

D = "C:/visual projects/parser/data/"

MASS = ["whackdoor", "bugnotfeature", "technomedia", "exploitex", "naebnet",
        "trends", "technomotel", "hiaimedia", "rozetked", "d_code", "gptpublic"]
EXPERTS = ["xor_journal", "neuraldvig", "data_secrets", "seeallochnaya",
           "denissexy", "ai_newz", "cgevent", "NeuralShit",
           "ai_machinelearning_big_data", "tproger", "tlive"]
ALL = MASS + EXPERTS

PAGES_PER_CH = 12      # 12 страниц × ~18 постов ≈ 200 постов на канал
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
NUM = re.compile(r"(\d[\d\s\u00a0]*)")
EMOJI_TAIL = re.compile(r"^(.*?)(\d[\d\s\u00a0]*)$", re.S)
DELAY = 2.0            # Telegram деградирует страницы при частых запросах
MAX_WORKERS = 1        # 1 = последовательно. >1 = потеря блоков реакций


def num(s):
    if not s:
        return None
    s = re.sub(r"[\s\u00a0]", "", str(s)).replace(" ", "")
    m = re.match(r"^([\d.,]+)([KM]?)$", s.upper())
    if not m:
        return None
    try:
        v = float(m.group(1).replace(",", "."))
    except ValueError:
        return None
    return v * {"K": 1e3, "M": 1e6}.get(m.group(2), 1)


def parse_reactions(msg):
    """Каждая .tgme_reaction — это фишка: [эмодзи] + число.

    ВАЖНО: итогового элемента в блоке НЕТ. Раньше первая фишка
    ошибочно трактовалась как итог, из-за чего каналы, у которых
    первой шла фишка с эмодзи, давали 0.

    Разметка:
      <i class="emoji"><b>😁</b></i>139     — обычный эмодзи
      <tg-emoji emoji-id="..."></tg-emoji>274 — кастомный эмодзи
    Итог = сумма ВСЕХ фишек.
    """
    block = msg.select_one(".tgme_widget_message_reactions")
    if not block:
        return 0, {}
    br = {}
    for e in block.select(".tgme_reaction"):
        custom = e.find("tg-emoji") is not None
        emo = "" if custom else e.get_text(" ", strip=True).strip()
        emo = re.sub(r"[\d\s\u00a0]+$", "", emo).strip()
        cnt = num(NUM.search(e.get_text(" ", strip=True)).group(1)) if NUM.search(
            e.get_text(" ", strip=True)) else None
        if cnt is None:
            continue
        key = "custom" if custom else (emo or "?")
        br[key] = br.get(key, 0) + cnt
    return sum(br.values()), br


def parse_page(html):
    s = BeautifulSoup(html, "html.parser")
    out = []
    for m in s.select("div.tgme_widget_message[data-post]"):
        pid = m.get("data-post") or ""
        mid = int(pid.split("/")[-1]) if "/" in pid and pid.split("/")[-1].isdigit() else None
        v = m.select_one(".tgme_widget_message_views")
        views = num(v.get_text(strip=True)) if v else None
        t = m.select_one(".tgme_widget_message_text")
        text = t.get_text(" ", strip=True) if t else ""
        fwd = m.select_one(".tgme_widget_message_forwarded_from_name")
        fwd_name = fwd.get_text(" ", strip=True) if fwd else None
        date_el = m.select_one("time[datetime]")
        dt = date_el.get("datetime") if date_el else None
        total_rx, br = parse_reactions(m)
        has_media = bool(m.select_one(".tgme_widget_message_photo_wrap, "
                                      ".tgme_widget_message_video_wrap, "
                                      ".tgme_widget_message_gif_wrap, "
                                      ".tgme_widget_message_document"))
        out.append({
            "id": mid, "views": views, "dt": dt, "text": text,
            "len": len(text), "fwd": fwd_name, "media": has_media,
            "rx": total_rx, "rx_break": br,
            "n_links": len(re.findall(r"https?://", text)),
        })
    return out


def fetch_channel(ch):
    sess = requests.Session()
    sess.headers.update({"User-Agent": UA,
                          "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"})
    subs_el = None
    try:
        r0 = sess.get(f"https://t.me/s/{ch}", timeout=30)
        if r0.status_code != 200:
            return ch, [], None, r0.status_code
        s0 = BeautifulSoup(r0.text, "html.parser")
        c = s0.select_one(".tgme_channel_info_counter .counter_value")
        subs_el = num(c.get_text(strip=True)) if c else None
    except Exception as e:
        return ch, [], None, str(e)[:40]

    posts, seen, before = [], set(), None
    blocks_seen = 0
    for _ in range(PAGES_PER_CH):
        url = f"https://t.me/s/{ch}" + (f"?before={before}" if before else "")
        try:
            r = sess.get(url, timeout=30)
            if r.status_code != 200:
                break
            s = BeautifulSoup(r.text, "html.parser")
            n_msgs = len(s.select("div.tgme_widget_message[data-post]"))
            n_rx = len(s.select(".tgme_widget_message_reactions"))
            blocks_seen += n_rx
            page = parse_page(r.text)
            if not page:
                break
            new = [p for p in page if p["id"] and p["id"] not in seen]
            for p in new:
                seen.add(p["id"])
            posts.extend(new)
            before = min(p["id"] for p in page if p["id"]) if any(p["id"] for p in page) else None
            if not before or not new:
                break
            time.sleep(DELAY + random.random() * 0.5)
        except Exception:
            break
    return ch, posts, subs_el, blocks_seen


print(f"Собираю {len(ALL)} каналов × до {PAGES_PER_CH} страниц, "
      f"задержка {DELAY}s, воркеров {MAX_WORKERS}", file=sys.stderr)
res = {}
with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
    for ch, posts, subs, blocks in ex.map(fetch_channel, ALL):
        res[ch] = {"subs": subs, "posts": posts}
        has_rx = sum(1 for p in posts if p["rx"])
        cov = f"{has_rx/len(posts)*100:5.1f}%" if posts else "  -  "
        print(f"  {ch:30s} subs={str(subs):>12s}  постов={len(posts):4d}  "
              f"с реакциями={has_rx:4d} ({cov})  блоков={blocks:4d}", file=sys.stderr)

json.dump(res, open(D + "reactions.json", "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)

tot = sum(len(v["posts"]) for v in res.values())
rx = sum(1 for v in res.values() for p in v["posts"] if p["rx"])
print(f"\nИТОГО: {tot} постов, из них с реакциями {rx} ({rx/tot*100:.1f}%)",
      file=sys.stderr)
print(f"-> {D}reactions.json", file=sys.stderr)
