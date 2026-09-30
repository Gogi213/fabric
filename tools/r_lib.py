"""Общие функции для исследований R2–R6: загрузка корпуса, очистка текста, формат поста, реклама."""
import glob, gzip, json, os, re
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CORPUS = os.path.join(ROOT, "data", "r", "corpus")
ALIASES = {"tehnochat": "technomedia"}

URL = re.compile(r"https?://\S+")
EMO = re.compile("[\U0001F000-\U0001FAFF☀-➿️‍⃣]")
# рекламная маркировка: «Реклама. Рекламодатель …», erid в тексте или в ссылке (& часто как &amp;)
AD_MARK = re.compile(r"(\berid\b|#реклама|#ad\b|реклама\.?\s*(рекламодатель|ооо|ип\b|ао\b|пао)|на правах рекламы)", re.I)
ERID_URL = re.compile(r"\berid=", re.I)
ADVERTISER = re.compile(r"рекламодатель[:\s]+(.{3,80}?)(?:[.,;]\s*(?:инн|огрн|erid)|\s+инн|$)", re.I)
INN = re.compile(r"\bИНН[:\s]*(\d{10,12})", re.I)


def load(pattern="*.json.gz", meta_only=False):
    """{handle: record} для всех собранных каналов (без алиасов)."""
    out = {}
    for p in sorted(glob.glob(os.path.join(CORPUS, pattern))):
        if p.endswith(".meta.json.gz") != meta_only:
            continue
        try:
            d = json.load(gzip.open(p, "rt", encoding="utf-8"))
        except Exception:
            continue
        if d["handle"] in ALIASES:
            continue
        for q in d["posts"]:
            q["_ch"] = d["handle"]
            q["_t"] = datetime.fromisoformat(q["dt"]) if q.get("dt") else None
        out[d["handle"]] = d
    return out


def clean(text, handle=None):
    t = URL.sub(" ", text or "")
    t = EMO.sub(" ", t)
    if handle:
        t = re.sub(rf"@?{re.escape(handle)}\b", " ", t, flags=re.I)
    return re.sub(r"\s+", " ", t).strip()


def post_format(p):
    """Вид поста по содержимому."""
    m = p.get("media") or {}
    if p.get("fwd_name"):
        return "форвард"
    if m.get("poll"):
        return "опрос"
    if m.get("round"):
        return "кружок"
    if m.get("audio"):
        return "аудио"
    if m.get("sticker"):
        return "стикер"
    if m.get("video") and m.get("album_items"):
        return "альбом (с видео)"
    if m.get("album_items"):
        return "альбом"
    if m.get("video"):
        return "видео"
    if m.get("photo"):
        return "фото"
    if m.get("document"):
        return "файл"
    if p.get("preview"):
        return "текст + превью ссылки"
    if p.get("text"):
        return "текст"
    return "прочее"


def own_link(u, handle):
    m = re.search(r"(?:t\.me|telegram\.me)/([A-Za-z0-9_]+)", u)
    return bool(m and m.group(1).lower() in {handle.lower()} | {a for a, b in ALIASES.items() if b == handle})


def is_marked_ad(p):
    if AD_MARK.search(p.get("text") or ""):
        return True
    return any(ERID_URL.search(u) and not own_link(u, p["_ch"]) for u, _ in p.get("links") or [])


def advertiser(p):
    t = p.get("text") or ""
    m = ADVERTISER.search(t)
    inn = INN.search(t)
    name = re.sub(r"\s+", " ", m.group(1)).strip(" .,«»\"") if m else None
    return name, (inn.group(1) if inn else None)
