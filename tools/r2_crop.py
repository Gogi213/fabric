"""R2. Выравнивание окна дособранных каналов по основному корпусу.

Основной корпус собран 30.09 23:32 – 01.10 01:32 UTC (окно 14 суток назад от момента сбора).
265 каналов дособраны 01.10 днём; их посты обрезаются до общего окна [END − 14 сут; END],
END = самый поздний момент сбора основного корпуса. Иначе посты после END выглядели бы
как сюжеты, которые эти каналы «опубликовали первыми».

Запуск: python tools/r2_crop.py   (идемпотентно: уже обрезанные файлы не трогает)
"""
import glob, gzip, json, os
from datetime import datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
END = datetime.fromisoformat("2026-10-01T01:32:06.637900+00:00")
START = END - timedelta(days=14)

n_files = n_drop = 0
for p in glob.glob(os.path.join(ROOT, "data", "r", "corpus", "*.json.gz")):
    if p.endswith(".meta.json.gz"):
        continue
    d = json.load(gzip.open(p, "rt", encoding="utf-8"))
    c = d["crawl"]
    if datetime.fromisoformat(c["fetched_at"]) <= END or c.get("cropped_to"):
        continue
    before = len(d["posts"])
    d["posts"] = [x for x in d["posts"] if x.get("dt") and START <= datetime.fromisoformat(x["dt"]) <= END]
    c["cropped_to"] = [START.isoformat(), END.isoformat()]
    c["posts_before_crop"] = before
    json.dump(d, gzip.open(p, "wt", encoding="utf-8"), ensure_ascii=False)
    n_files += 1
    n_drop += before - len(d["posts"])
print(f"обрезано файлов: {n_files}, отброшено постов вне окна: {n_drop}")
