# Pflanzen Scraper

Скрипт для сбора данных из категории **Pflanzen** на сайте [Florist Online Shop](https://www.floristonlineshop.de/pflanzenonlineshop).

## Возможности
- Обходит все страницы раздела **Pflanzen** (с поддержкой пагинации).
- Для каждого товара собирает:
  - `id` — порядковый номер;
  - `type` — константа `Pflanzen`;
  - `name` — название товара;
  - `about` — краткое описание (из JSON-LD или текста рядом с заголовком);
  - `price_from` — минимальная цена в формате `NN.NN`.
- Результат сохраняется в `pflanzen.csv` (UTF-8, разделитель запятая).

## Установка
1. Клонируйте репозиторий:
   ```bash
   git clone https://github.com/<your-repo>/pflanzen-scraper.git
   cd pflanzen-scraper
2. Установите зависимости:
   ```bash
    pip install -r requirements.txt
3. Запуск
   ```bash
   python pflanzen_scraper.py
После выполнения в корне проекта появится файл pflanzen.csv.
