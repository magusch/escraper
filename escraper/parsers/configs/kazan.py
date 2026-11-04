"""ConfigScraper sites in Казань.

Venues: Татарская филармония им. Тукая, Национальный музей РТ.
Candidates and rejected sites: docs/kazan_sites.md.

Addresses are given without the city (see utils.strip_city convention).
"""

KAZAN_SITES = {
    "tatfil": {
        "name": "tatfil",
        "source": "TFIL",
        "city": "kazan",
        "base_url": "https://tatfil.ru",
        # Tickets: own box office tickets.tatfil.ru (not kassir/afisha)
        "listing_url": "/poster/",
        # --- listing selectors ---
        # Only the nearest ~8 events are in the HTML; further dates come via a
        # POST (filter_date) the scraper can't make — daily runs cover it.
        "card_selector": ".poster-item",
        "card_title_selector": ".poster-item__info-desc",
        "card_date_selector": ".poster-item__date",  # "03 Ноября ВТ"
        "card_image_selector": "img.picture-img",
        "card_image_attr": "srcset",
        "card_link_selector": "a",
        "card_price_selector": ".poster-item__price",  # "1500 - 2800 руб."
        # Label "Балет" / "Татарская вокальная музыка" → keyword detection
        "card_category_selector": ".poster-item__info .label",
        "card_category_detect": True,
        # --- detail page selectors ---
        # Text is spread over many <p>; the price/duration <p> sit deeper
        # (inside .article-enumeration) and are not matched
        "description_selector": "article > p",
        "description_all": True,
        "time_selector": ".tickets-item__info",  # "03 Ноября 19:00"
        "price_selector": None,
        # --- date ---
        "date_format": "russian",
        # --- defaults ---
        # No default_category: concerts, ballet, kids' shows mix
        "default_address": "ул. Павлюхина, 73",
        "default_place": "Татарская филармония им. Тукая",
    },
    "tatmuseum": {
        "name": "tatmuseum",
        "source": "NMRT",
        "city": "kazan",
        "base_url": "https://tatmuseum.ru",
        "listing_url": "/events/",
        # --- listing selectors ---
        # Page 1 holds the dated events; pages 2+ are permanent/online
        # exhibitions and undated classes — no pagination needed.
        "card_selector": "a.event",
        "card_title_selector": ".event__title",
        # "Выставка | 8 октября – 12 декабря", "Практикум | 2-7 ноября", "Акция"
        "card_date_selector": ".event__type",
        "card_description_selector": ".event__desc",
        # Type before the date ("Выставка | …") → keyword detection
        "card_category_selector": ".event__type",
        "card_category_detect": True,
        "card_image_selector": ".event__img img",
        "card_image_attr": "src",
        # --- detail page selectors ---
        "description_selector": ".news-text",
        "time_selector": None,
        "price_selector": None,
        # --- date ---
        "date_format": "russian",
        "default_time": "10:00",
        # Undated cards ("Акция", "Квест | 7+") are standing offers — skip
        "require_date": True,
        # --- defaults ---
        "default_address": "Кремлёвская ул., 2",
        "default_place": "Национальный музей Республики Татарстан",
    },
}
