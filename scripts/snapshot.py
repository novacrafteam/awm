#!/usr/bin/env python3
"""Зберігає знімок карти Google Мої карти в папку history/ (запускається автоматично на GitHub).

Що робить:
  1. Завантажує поточну карту (KML) за її mid.
  2. Порівнює зміст з останнім збереженим знімком.
  3. Якщо карта змінилась — записує history/РРРР-ММ-ДД.kml.gz (за київською датою; якщо за день
     змін було кілька, лишається останній стан дня) і оновлює history/index.json.
  4. Завжди оновлює history/latest.kml.gz — свіжа копія для сайту.
"""
import gzip, hashlib, io, json, os, re, sys, time, urllib.parse, urllib.request, zipfile
from datetime import datetime
from zoneinfo import ZoneInfo

HIST = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "history")
INDEX = os.path.join(HIST, "index.json")


def canon_hash(kml: bytes) -> str:
    """Хеш лише змісту карти (назви, стилі, координати) — щоб дрібниці формату не давали «нових версій»."""
    text = kml.decode("utf-8", "replace")
    blocks = re.findall(r"<Placemark.*?</Placemark>", text, flags=re.S)
    norm = []
    for b in blocks:
        b = re.sub(r'\sid="[^"]*"', "", b)
        b = re.sub(r",0(?=\s|<)", "", b)
        b = re.sub(r"\s+", " ", b).strip()
        norm.append(b)
    return hashlib.sha256("\n".join(norm).encode("utf-8")).hexdigest()


HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/126.0.0.0 Safari/537.36",
    "Accept": "application/vnd.google-earth.kml+xml,application/xml,text/xml,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.google.com/maps/d/viewer",
}


def download(url: str, tries: int = 2) -> bytes:
    """Одне завантаження з кількома спробами; кидає виняток, якщо не вийшло."""
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            return urllib.request.urlopen(req, timeout=90).read()
        except Exception as e:                  # 403/429/5xx/таймаут
            last = e
            time.sleep(3 * (i + 1))
    raise last


def looks_like_kml(data: bytes) -> bool:
    if data[:2] == b"PK":
        return True
    return b"<kml" in data and b"<Placemark" in data


def fetch_kml() -> bytes:
    local = os.environ.get("KML_FILE")          # для перевірки без інтернету
    if local:
        data = open(local, "rb").read()
    else:
        mid = urllib.parse.quote(os.environ["MAP_ID"], safe="")
        u1 = f"https://www.google.com/maps/d/kml?mid={mid}&forcekml=1"
        u2 = f"https://www.google.com/maps/d/u/0/kml?mid={mid}&forcekml=1"
        # Google часто віддає 403 IP-адресам GitHub-серверів, тому далі йдуть запасні шляхи через проксі
        # (вони ходять до Google зі своїх адрес). Той самий підхід використовує й сам сайт.
        candidates = [
            u1, u2,
            "https://corsproxy.io/?url=" + urllib.parse.quote(u1, safe=""),
            "https://api.allorigins.win/raw?url=" + urllib.parse.quote(u1, safe=""),
            "https://corsproxy.io/?url=" + urllib.parse.quote(u2, safe=""),
        ]
        data, errors = None, []
        for url in candidates:
            try:
                d = download(url)
            except Exception as e:
                errors.append(f"{url.split('?')[0]} -> {e}")
                print("Не вийшло:", errors[-1], file=sys.stderr)
                continue
            if looks_like_kml(d):
                data = d
                print("Карту отримано через:", url.split("?")[0])
                break
            errors.append(f"{url.split('?')[0]} -> відповідь не схожа на KML")
            print("Не вийшло:", errors[-1], file=sys.stderr)
        if data is None:
            raise SystemExit("Не вдалося завантажити карту жодним способом:\n  " + "\n  ".join(errors)
                             + "\nПеревір, що карта відкрита для перегляду за посиланням.")
    if data[:2] == b"PK":                       # KMZ → дістаємо doc.kml
        z = zipfile.ZipFile(io.BytesIO(data))
        name = next(n for n in z.namelist() if n.lower().endswith(".kml"))
        data = z.read(name)
    if b"<kml" not in data:
        raise SystemExit("Відповідь не схожа на KML — знімок не збережено (карта закрита для перегляду?).")
    return data


def main():
    os.makedirs(HIST, exist_ok=True)
    data = fetch_kml()
    h = canon_hash(data)
    idx = {"snapshots": []}
    if os.path.exists(INDEX):
        idx = json.load(open(INDEX, encoding="utf-8"))
    snaps = idx.get("snapshots", [])
    gz = gzip.compress(data, 9, mtime=0)
    open(os.path.join(HIST, "latest.kml.gz"), "wb").write(gz)

    if snaps and snaps[-1].get("h") == h:
        print("Змін немає — новий знімок не потрібен.")
        return
    today = datetime.now(ZoneInfo("Europe/Kyiv")).date().isoformat()
    fname = f"{today}.kml.gz"
    open(os.path.join(HIST, fname), "wb").write(gz)
    entry = {"d": today, "f": fname, "h": h}
    if snaps and snaps[-1]["d"] == today:
        snaps[-1] = entry                       # той самий день — оновлюємо стан дня
    else:
        snaps.append(entry)
    idx["snapshots"] = snaps
    json.dump(idx, open(INDEX, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("Збережено знімок", fname)


if __name__ == "__main__":
    main()
