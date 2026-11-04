"""ConfigScraper sites in Санкт-Петербург.

Venues: Севкабель Порт, Новая Голландия, Левашовский хлебозавод, Русский музей,
Эрарта (выставки + промо-анонсы), Филармония им. Шостаковича, Дом Радио,
Александринский театр.

Addresses are given without the city (see utils.strip_city convention).
"""

SPB_SITES = {
    "sevcable": {
        "name": "sevcable",
        "source": "SEVC",
        "city": "spb",
        "base_url": "https://sevcableport.ru",
        "listing_url": "/afisha/",
        # --- listing selectors ---
        "card_selector": "a.event_card",
        "card_title_selector": ".event_name",
        "card_date_selector": ".event_surname",
        "card_category_selector": ".event_type",
        "card_image_selector": ".event_foto_img",
        "card_image_attr": "data-src",
        # --- detail page selectors ---
        "description_selector": ".infopage_text_flex",
        "time_selector": ".infopage_time_val",
        "place_selector": ".infopage_time .item_w_dot",
        "price_selector": None,
        # --- date ---
        "date_format": "russian",
        # --- defaults ---
        "default_address": "Кожевенная линия, 40",
        "default_place": "Севкабель Порт",
    },
    "newholland": {
        "name": "newholland",
        "source": "NHOL",
        "city": "spb",
        "base_url": "https://www.newhollandsp.ru",
        "listing_url": "/events/",
        # --- listing selectors ---
        "card_selector": "a.event",
        "card_title_selector": ".event-name",
        "card_date_selector": ".event-date",
        "card_image_selector": "img",
        "card_image_attr": "src",
        # --- detail page selectors ---
        "description_selector": ".col-sm-8",
        # Site dropped the structured .prop.TIME block; session times now live
        # in free text — fall back to DEFAULT_EVENT_HOUR.
        "time_selector": None,
        "price_selector": None,
        # --- date ---
        "date_format": "%d.%m.%Y",
        # --- defaults ---
        "default_address": "наб. Адмиралтейского канала, 2",
        "default_place": "Новая Голландия",
    },
    "levashovsky": {
        "name": "levashovsky",
        "source": "LVSH",
        "city": "spb",
        "base_url": "https://levashovsky.ru",
        "listing_url": "/afisha",
        # --- listing selectors ---
        "card_selector": ".t390",
        "card_title_selector": ".t390__title",
        "card_date_selector": ".t390__uptitle",
        "card_description_selector": ".t390__descr",
        "card_image_selector": ".t390__img",
        "card_image_attr": "data-original",
        "card_link_selector": "a",
        # --- detail page ---
        "skip_detail": True,
        # --- date ---
        "date_format": "russian",
        # --- defaults ---
        "default_address": "Барочная ул., 4А",
        "default_place": "Левашовский хлебозавод",
    },
    "rusmuseum": {
        "name": "rusmuseum",
        "source": "RUSM",
        "city": "spb",
        "base_url": "https://rusmuseum.ru",
        "listing_url": "/exhibitions/current/",
        # --- listing selectors ---
        "card_selector": ".tile.card",
        "card_title_selector": "h3.event-title-name",
        "card_date_selector": ".event-date",
        "card_image_selector": "img.image-card",
        "card_image_attr": "src",
        "card_description_selector": ".event-about-text",
        "card_link_selector": "a.building",
        "card_place_selector": "a.building",
        # --- detail page ---
        # Detail pages are client-side rendered (Vue) — no server HTML to parse
        "skip_detail": True,
        # --- date ---
        "date_format": "russian",
        "default_time": "10:00",
        # --- defaults ---
        "default_category": "выставки",
        "default_address": "Инженерная ул., 4",
        "default_place": "Русский музей",
        "places": {
            "Михайловский дворец": "Инженерная ул., 4",
            "Корпус Бенуа": "наб. канала Грибоедова, 2",
            "Мраморный дворец": "Миллионная ул., 5/1",
            "Строгановский дворец": "Невский пр., 17",
            "Михайловский замок": "Садовая ул., 2",
            "Западный павильон Михайловского замка": "Инженерная ул., 8",
            "Домик Петра I": "Петровская наб., 6",
        },
    },
    "erarta": {
        "name": "erarta",
        "source": "ERAR",
        "city": "spb",
        "base_url": "https://www.erarta.com",
        # Exhibitions filter of the calendar — /ru/calendar/ may also list
        # concerts and other events, so default_category stays correct
        "listing_url": "/ru/calendar/exhibitions/",
        # --- listing selectors ---
        "card_selector": "li.events__item:not(.promoted)",
        "card_title_selector": ".events__item-name",
        "card_date_selector": ".events__item-date",
        "card_image_selector": "img",
        "card_image_attr": "src",
        "card_link_selector": "a.events__item-name",
        # --- detail page selectors ---
        "description_selector": ".content",
        # Site header: "сегодня музей работает с 11:00 до 23:00" —
        # gives both opening (date_from) and closing (date_to) time
        "time_selector": ".header__info-text",
        "price_selector": None,
        # --- date ---
        "date_format": "russian",
        "default_time": "11:00",
        # --- defaults ---
        "default_category": "выставки",
        "default_address": "29-я линия В.О., 2",
        "default_place": "Эрарта",
    },
    "erarta_news": {
        # Promoted calendar cards (concerts, one-off events) — they link to a
        # news article instead of an event page, so they are excluded from
        # "erarta" and handled here. Run both configs to cover the calendar.
        "name": "erarta_news",
        "source": "ERAR",
        "city": "spb",
        "base_url": "https://www.erarta.com",
        "listing_url": "/ru/calendar/exhibitions/",
        "card_selector": "li.events__item.promoted",
        "card_title_selector": ".events__item-name",
        "card_date_selector": ".events__item-desc",
        "card_image_selector": None,
        "card_image_attr": "style",
        "card_link_selector": "a.events__item-link",
        "description_selector": ".content:has(p)",
        "time_selector": None,
        "price_selector": None,
        "date_format": "russian",
        "require_date": True,
        "default_address": "29-я линия В.О., 2",
        "default_place": "Эрарта",
    },
    "philharmonia": {
        "name": "philharmonia",
        "source": "PHIL",
        "city": "spb",
        # Site serves windows-1251; the Content-Type header declares it,
        # so requests decodes response.text correctly
        "base_url": "https://www.philharmonia.spb.ru",
        "listing_url": "/afisha/",
        # --- listing selectors ---
        # .more_items distinguishes the events container from header nav icons
        "card_selector": "._items.more_items ._item",
        "card_title_selector": "._title",
        "card_date_selector": "._date_from",  # "13 июля , 2026 12:00 , Пн"
        "card_image_selector": "._image img",
        "card_image_attr": "src",
        "card_link_selector": "._title a",
        "card_place_selector": "._hall",
        "card_price_selector": ".it-buy-prices",
        # --- detail page selectors ---
        "description_selector": ".afisha_element_dett",
        "time_selector": None,
        "price_selector": None,
        # --- date ---
        "date_format": "russian",
        # --- pagination ---
        # Month navigation; the year in the URL is the season start year
        # (season runs September–August): ?year=2025&month=8 → August 2026
        "pagination": {
            "type": "month",
            "url_template": "?year={year}&month={month}",
            "months_ahead": 2,
            "season_start_month": 9,
        },
        # --- defaults ---
        # No default_category: concerts and excursions mix — detect_category
        # handles them by title/description keywords
        "default_address": "Михайловская ул., 2",
        "default_place": "Филармония им. Шостаковича",
        "places": {
            "Большой зал": "Михайловская ул., 2",
            "Малый зал": "Невский пр., 30",
        },
    },
    "domradio": {
        "name": "domradio",
        "source": "DOMR",
        "city": "spb",
        "base_url": "https://dom.radio",
        "listing_url": "/",
        # --- listing selectors ---
        "card_selector": "div.event-item",
        "card_title_selector": ".event-item-name",
        "card_date_selector": ".event-item-date",  # "15 июля, 19:00" / "21 июня – 12 июля"
        "card_description_selector": ".event-item-text",
        # Off-site events carry the venue address right on the card
        "card_address_selector": ".event-item-type",
        "card_link_selector": "a",  # often absent or external (tickets/forms)
        # --- detail page ---
        # No per-event pages on the site — everything lives on the listing
        "skip_detail": True,
        # --- date ---
        "date_format": "russian",
        # Programme teasers and open calls have no date — skip them
        "require_date": True,
        # --- defaults ---
        "default_address": "Итальянская ул., 27",
        "default_place": "Дом Радио",
    },
    "alexandrinsky": {
        "name": "alexandrinsky",
        "source": "ALXN",
        "city": "spb",
        "base_url": "https://alexandrinsky.ru",
        "listing_url": "/afisha-i-bilety/",
        # --- listing selectors ---
        "card_selector": "div.box-poster-tickets",
        "card_title_selector": "h4",
        "card_date_selector": ".repertoire-date-list__item",
        "card_category_selector": ".box-addition-description",
        "card_image_selector": "img",
        "card_image_attr": "src",
        "card_description_selector": ".box-poster-tickets-txt",
        "card_link_selector": "h4 a",
        "card_place_selector": ".box-schedule span",
        # --- detail page ---
        "skip_detail": True,
        # --- date ---
        "date_format": "russian",
        # --- defaults ---
        "default_address": "пл. Островского, 6",
        "default_place": "Александринский театр",
        "places": {
            "Основная сцена": "пл. Островского, 6",
            "Новая сцена": "наб. реки Фонтанки, 49А",
        },
    },
}
