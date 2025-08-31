import requests
from bs4 import BeautifulSoup
import csv
import re
import time
import json
from urllib.parse import urljoin, urlparse, parse_qs

BASE_URL = "https://www.floristonlineshop.de"
START_URL = f"{BASE_URL}/pflanzenonlineshop"
OUT_CSV = "pflanzen.csv"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; PflanzenScraper/1.0; +https://example.com/bot)",
    "Accept-Language": "de,en;q=0.8,ru;q=0.6",
}

# --- цены ---
RE_PREIS_AB_EURO = re.compile(r"Preis\s*ab[^\d€]*€?\s*([0-9][\d.,]*)", re.I)
RE_EURO_ANY = re.compile(r"€\s*([0-9][\d.,]*)")

def normalize_number(num: str) -> str:
    """ 25,00 / 25.00 / 1.234,56 / 1,234.56 -> NN.NN """
    s = (num or "").strip()
    if not s:
        return "0.00"
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")  # 1.234,56 -> 1234.56
        else:
            s = s.replace(",", "")  # 1,234.56 -> 1234.56
    else:
        if "," in s:
            s = s.replace(".", "").replace(",", ".")
    try:
        return f"{float(s):.2f}"
    except ValueError:
        return "0.00"

def extract_price_from_text(text: str) -> str:
    m = RE_PREIS_AB_EURO.search(text or "")
    if not m:
        m = RE_EURO_ANY.search(text or "")
    return normalize_number(m.group(1)) if m else "0.00"

# --- утилиты страницы ---
def get_soup(url: str) -> BeautifulSoup:
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return BeautifulSoup(r.text, "html.parser")

def slice_before_similar_products_html(html: str) -> str:
    i = html.lower().find("ähnliche produkte")
    return html[:i] if i > 0 else html

def slice_before_similar_products_soup(soup: BeautifulSoup) -> BeautifulSoup:
    html = slice_before_similar_products_html(str(soup))
    return BeautifulSoup(html, "html.parser")

def collect_product_links_from_listing(soup: BeautifulSoup) -> list[str]:
    """Собираем ссылки /product-page/ из разметки категории (после отсечения 'Ähnliche Produkte')."""
    soup = slice_before_similar_products_soup(soup)
    links, seen = [], set()
    for a in soup.select('a[href*="/product-page/"]'):
        href = a.get("href") or ""
        if not href:
            continue
        href = urljoin(BASE_URL, href)
        path = urlparse(href).path
        if path in seen:
            continue
        seen.add(path)
        links.append(href)
    return links

def find_next_pages(soup: BeautifulSoup, current_url: str) -> list[str]:
    """Ищем пагинацию в пределах /pflanzenonlineshop: rel=next, цифры/Weiter, ?page="""
    urls = set()

    # rel="next"
    for a in soup.select("a[rel='next']"):
        if a.get("href"):
            urls.add(urljoin(current_url, a["href"]))

    for a in soup.find_all("a", href=True):
        txt = a.get_text(" ", strip=True)
        # явные номера/стрелки
        if re.fullmatch(r"(Weiter|Next|Nächste|›|»|\d{1,3})", (txt or ""), flags=re.I):
            urls.add(urljoin(current_url, a["href"]))
        # параметр ?page=
        h = urljoin(current_url, a["href"])
        qs = parse_qs(urlparse(h).query)
        if "page" in qs:
            urls.add(h)

    urls = {u for u in urls if "/pflanzen" in urlparse(u).path.lower()}
    return sorted(urls)

# --- JSON-LD и детали товара ---
def jsonld_iter(soup: BeautifulSoup):
    for tag in soup.select('script[type="application/ld+json"]'):
        txt = tag.string or tag.get_text()
        if not txt:
            continue
        try:
            data = json.loads(txt)
        except Exception:
            continue
        if isinstance(data, list):
            for obj in data:
                yield obj
        else:
            yield data

def extract_from_jsonld(soup: BeautifulSoup):
    """Возвращает (name, description, min_price) из JSON-LD, если есть."""
    name = None
    description = None
    prices = []
    def add_price(v):
        if v is None:
            return
        prices.append(normalize_number(str(v)))
    for obj in jsonld_iter(soup):
        if not isinstance(obj, dict):
            continue
        t = obj.get("@type")
        tset = set(t if isinstance(t, list) else [t])
        if "Product" in tset:
            name = name or obj.get("name")
            description = description or obj.get("description")
            offers = obj.get("offers")
            if isinstance(offers, dict):
                if offers.get("@type") == "AggregateOffer":
                    add_price(offers.get("lowPrice"))
                else:
                    add_price(offers.get("price"))
            elif isinstance(offers, list):
                for off in offers:
                    add_price(off.get("price"))
        if "Offer" in tset or "AggregateOffer" in tset:
            add_price(obj.get("lowPrice") or obj.get("price"))
    price_from = min(prices) if prices else None
    return name, (description.strip() if isinstance(description, str) else None), price_from

def extract_about_fallback(soup: BeautifulSoup, title_el) -> str:
    """Короткое описание рядом с заголовком, если JSON-LD не дал description."""
    cands = []
    if title_el:
        if title_el.parent:
            t = title_el.parent.get_text(" ", strip=True)
            if t and "Preis" not in t and len(t) <= 220:
                cands.append(t)
        p = title_el.find_next("p")
        if p:
            t = p.get_text(" ", strip=True)
            if t and "Preis" not in t and len(t) <= 220:
                cands.append(t)
    cands = [re.sub(r"\s+", " ", c).strip() for c in cands if c and len(c) >= 12]
    return min(cands, key=len) if cands else "siehe Foto"

def parse_product_page(url: str) -> dict:
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    # name
    h = soup.find(["h1", "h2"])
    name = h.get_text(strip=True) if h else None

    # JSON-LD
    jl_name, jl_desc, jl_price = extract_from_jsonld(soup)
    if not name and jl_name:
        name = jl_name

    # about
    about = jl_desc or extract_about_fallback(soup, h)
    if about and len(about) > 220:
        about = about[:217].rstrip() + "…"

    # price_from: JSON-LD приоритетно, иначе из текста
    price_from = jl_price if jl_price else None
    if not price_from:
        chunks = []
        if h and h.parent:
            chunks.append(h.parent.get_text(" ", strip=True))
        chunks.append(soup.get_text(" ", strip=True))
        for t in chunks:
            price_from = extract_price_from_text(t)
            if price_from != "0.00":
                break
    price_from = price_from or "0.00"

    return {
        "type": "Pflanzen",
        "name": (name or "Unbekannt").strip(),
        "about": (about or "siehe Foto").strip(),
        "price_from": price_from,
    }

def crawl_category(start_url: str) -> list[dict]:
    products = []
    seen_paths = set()
    visited_pages = set()
    to_visit = [start_url]

    while to_visit:
        url = to_visit.pop(0)
        if url in visited_pages:
            continue
        visited_pages.add(url)

        soup = get_soup(url)

        product_links = collect_product_links_from_listing(soup)

        next_pages = find_next_pages(soup, url)
        for nu in next_pages:
            if nu not in visited_pages and nu not in to_visit:
                to_visit.append(nu)

        for href in product_links:
            path = urlparse(href).path
            if path in seen_paths:
                continue
            seen_paths.add(path)

            try:
                item = parse_product_page(href)
            except Exception:
                item = {
                    "type": "Pflanzen",
                    "name": "Unbekannt",
                    "about": "siehe Foto",
                    "price_from": "0.00",
                }
            products.append(item)
            time.sleep(0.15)

        time.sleep(0.2)

    return products

def write_csv(rows: list[dict], path: str):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["id", "type", "name", "about", "price_from"])
        for i, p in enumerate(rows, start=1):
            w.writerow([i, p["type"], p["name"], p["about"], p["price_from"]])

def scrape():
    products = crawl_category(START_URL)
    write_csv(products, OUT_CSV)
    print(f"Готово, собрано {len(products)} товаров. Файл: {OUT_CSV}")

if __name__ == "__main__":
    scrape()
