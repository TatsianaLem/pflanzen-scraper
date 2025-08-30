import requests
from bs4 import BeautifulSoup
import csv
import re
import time
from urllib.parse import urljoin, urlparse

BASE_URL = "https://www.floristonlineshop.de"
START_URL = f"{BASE_URL}/pflanzenonlineshop"

# Ищем число рядом с "Preis ab" или знаком €
RE_PREIS_AB_EURO = re.compile(r"Preis\s*ab[^\d€]*€?\s*([0-9][\d.,]*)", re.I)
RE_EURO_ANY = re.compile(r"€\s*([0-9][\d.,]*)")

def normalize_number(num: str) -> str:
    """ Превращает 25,00 / 25.00 / 1.234,56 / 1,234.56 -> NN.NN """
    s = num.strip()

    if "," in s and "." in s:
        last_comma = s.rfind(",")
        last_dot = s.rfind(".")
        if last_comma > last_dot:
            # 1.234,56 -> 1234.56
            s = s.replace(".", "").replace(",", ".")
        else:
            # 1,234.56 -> 1234.56
            s = s.replace(",", "")
    else:
        if "," in s:
            s = s.replace(".", "")
            s = s.replace(",", ".")
    try:
        return f"{float(s):.2f}"
    except ValueError:
        return "0.00"

def extract_price_from_text(text: str) -> str:
    """ Сначала ищем 'Preis ab €..', иначе — любое '€..' """
    m = RE_PREIS_AB_EURO.search(text)
    if not m:
        m = RE_EURO_ANY.search(text)
    return normalize_number(m.group(1)) if m else "0.00"

def slice_before_similar_products(html: str) -> str:
    i = html.lower().find("ähnliche produkte")
    return html[:i] if i > 0 else html

def price_from_detail(dsoup: BeautifulSoup) -> str:
    candidates = []
    h = dsoup.find(["h1", "h2"])
    if h:
        candidates.append(h.get_text(" ", strip=True))
        if h.parent:
            candidates.append(h.parent.get_text(" ", strip=True))
    candidates.append(dsoup.get_text(" ", strip=True))
    for t in candidates:
        p = extract_price_from_text(t)
        if p != "0.00":
            return p
    return "0.00"

def scrape():
    products = []

    r = requests.get(START_URL, timeout=30)
    r.raise_for_status()
    html = slice_before_similar_products(r.text)
    soup = BeautifulSoup(html, "html.parser")

    anchors = soup.select('a[href*="/product-page/"]')
    seen = set()

    for a in anchors:
        href = a.get("href") or ""
        if not href:
            continue
        if not href.startswith("http"):
            href = urljoin(BASE_URL, href)

        path = urlparse(href).path
        if path in seen:
            continue
        seen.add(path)

        try:
            d = requests.get(href, timeout=30)
            d.raise_for_status()
            dsoup = BeautifulSoup(d.text, "html.parser")

            h = dsoup.find(["h1", "h2"])
            name = h.get_text(strip=True) if h else "Unbekannt"

            price_from = price_from_detail(dsoup)

            products.append({
                "type": "Pflanzen",
                "name": name,
                "about": "siehe Foto",
                "price_from": price_from
            })
            time.sleep(0.3)
        except Exception:
            text = a.get_text(" ", strip=True)
            name = re.split(r"Preis\s*ab", text, flags=re.I)[0].strip() or "Unbekannt"
            products.append({
                "type": "Pflanzen",
                "name": name,
                "about": "siehe Foto",
                "price_from": "0.00"
            })

    # Пишем CSV
    with open("pflanzen.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["id", "type", "name", "about", "price_from"])
        for i, p in enumerate(products, start=1):
            w.writerow([i, p["type"], p["name"], p["about"], p["price_from"]])

    print(f"Готово, собрано {len(products)} товаров.")

if __name__ == "__main__":
    scrape()
