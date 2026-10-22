import os
import time

import pytest
import pytz
import requests
from datetime import datetime, timedelta
from pathlib import Path

from escraper.parsers import ConfigScraper
from escraper.parsers.config_scraper import SITES

from .testing import Response

MSK = pytz.timezone("Europe/Moscow")


@pytest.fixture(autouse=True)
def moscow_tz(monkeypatch):
    """Set system timezone to Moscow so astimezone() on naive datetimes works correctly."""
    monkeypatch.setenv("TZ", "Europe/Moscow")
    time.tzset()
    yield
    time.tzset()


TESTDATA = Path(__file__).parent / "test_data" / "test_config_scraper"

TEST_SITE_CONFIG = {
    "name": "testsite",
    "source": "TEST",
    "base_url": "https://testsite.example.com",
    "listing_url": "/afisha/",
    # --- listing selectors ---
    "card_selector": "a.event",
    "card_title_selector": ".event-name",
    "card_date_selector": ".event-date",
    "card_image_selector": "img",
    "card_image_attr": "src",
    # --- detail page selectors ---
    "description_selector": ".col-sm-8",
    "time_selector": ".prop.TIME",
    "price_selector": None,
    # --- date ---
    "date_format": "%d.%m.%Y",
    # --- defaults ---
    "default_address": "Test address, 1",
    "default_place": "Test Place",
}


@pytest.fixture(autouse=True)
def register_test_site():
    SITES["testsite"] = TEST_SITE_CONFIG
    yield
    SITES.pop("testsite", None)


#######################################
## config_scraper get_event
#######################################
def test_config_get_event_with_none():
    with pytest.raises(ValueError):
        ConfigScraper().get_event()


def test_config_get_event_without_site():
    with pytest.raises(ValueError):
        ConfigScraper().get_event(event_url="https://example.com/afisha/test/")


@pytest.fixture
def requests_get_event(monkeypatch):
    def get(url, **kwargs):
        with open(TESTDATA / "event_page_1.html") as f:
            text = f.read()
        return Response(ok=True, text=text)

    monkeypatch.setattr(requests, "get", get)


def test_config_get_event(requests_get_event):
    scraper = ConfigScraper()
    event_url = "https://testsite.example.com/afisha/concert-rock-2024/"

    card_data = {
        "url": event_url,
        "title": "Rock Concert 2024",
        "date_str": "15.06.2024",
        "image": "/upload/rock-concert.jpg",
    }

    event = scraper.get_event(event_url=event_url, site="testsite", card_data=card_data)

    assert event.title[2:] == "Rock Concert 2024"  # without emoji
    assert event.adress == "Test address, 1"
    assert event.category == "концерты"  # detected from title "Rock Concert"
    assert event.date_from == datetime(2024, 6, 15, 19, 30).astimezone(MSK)
    assert event.date_to == event.date_from + timedelta(hours=2)
    assert event.date_from_to == "15.06.2024"
    assert event.id == "CFG-TEST-concert-rock-2024"
    assert event.place_name == "Test Place"
    assert "amazing rock concert" in event.full_text
    assert event.poster_imag == "https://testsite.example.com/upload/rock-concert.jpg"
    assert event.url == event_url
    assert event.source == "CFG"
    assert event.is_registration_open is True
    # No price selector — no guessing from description text
    assert event.price == "на сайте"


def test_config_get_event_date_range(requests_get_event):
    """Test date range parsing like '01.07.2024–15.07.2024'."""
    scraper = ConfigScraper()
    event_url = "https://testsite.example.com/afisha/exhibition/"

    card_data = {
        "url": event_url,
        "title": "Art Exhibition",
        "date_str": "01.07.2024–15.07.2024",
        "image": "/upload/art.jpg",
    }

    event = scraper.get_event(event_url=event_url, site="testsite", card_data=card_data)

    assert event.date_from == datetime(2024, 7, 1, 19, 30).astimezone(MSK)
    # No closing time on page — end of the last day
    assert event.date_to == datetime(2024, 7, 15, 23, 59).astimezone(MSK)
    assert event.date_from_to == "01.07.2024–15.07.2024"


#######################################
## config_scraper get_events
#######################################
@pytest.fixture
def requests_get_events(monkeypatch):
    def get(url, **kwargs):
        if url.endswith("/afisha/"):
            filepath = TESTDATA / "listing_simple.html"
        else:
            filepath = TESTDATA / "event_page_1.html"
        with open(filepath) as f:
            text = f.read()
        return Response(ok=True, text=text)

    monkeypatch.setattr(requests, "get", get)


def test_config_get_events(requests_get_events):
    scraper = ConfigScraper()
    params = {"site": "testsite"}
    events = list(scraper.get_events(request_params=params))

    assert len(events) == 3

    ids = {e.id for e in events}
    assert "CFG-TEST-concert-rock-2024" in ids
    assert "CFG-TEST-exhibition-art-2024" in ids
    assert "CFG-TEST-lecture-science" in ids

    # Check that card data was picked up from listing
    for e in events:
        assert e.place_name == "Test Place"
        assert e.adress == "Test address, 1"
        assert e.poster_imag is not None


def test_config_get_events_skip_existed(requests_get_events):
    scraper = ConfigScraper()
    params = {"site": "testsite"}
    events = list(scraper.get_events(
        request_params=params,
        existed_event_ids=["CFG-TEST-concert-rock-2024"],
    ))

    assert len(events) == 2
    ids = {e.id for e in events}
    assert "CFG-TEST-concert-rock-2024" not in ids


def test_config_get_events_no_site():
    with pytest.raises(ValueError):
        list(ConfigScraper().get_events(request_params={}))


#######################################
## config_scraper helpers
#######################################
def test_parse_date_range_single():
    d_from, d_to, time_str = ConfigScraper._parse_date_range("17.02.2026")
    assert d_from == datetime(2026, 2, 17)
    assert d_to is None
    assert time_str is None


def test_parse_date_range_double():
    d_from, d_to, time_str = ConfigScraper._parse_date_range("01.11.2025–01.05.2026")
    assert d_from == datetime(2025, 11, 1)
    assert d_to == datetime(2026, 5, 1)
    assert time_str is None


def test_parse_date_range_empty():
    d_from, d_to, time_str = ConfigScraper._parse_date_range(None)
    assert d_from is None
    assert d_to is None
    assert time_str is None


def test_parse_russian_date_single():
    d_from, d_to, time_str = ConfigScraper._parse_date_range("1 февраля", "russian")
    assert d_from.month == 2
    assert d_from.day == 1
    assert d_to is None
    assert time_str is None


def test_parse_russian_date_range():
    d_from, d_to, time_str = ConfigScraper._parse_date_range("с 1 февраля по 28 февраля", "russian")
    assert d_from.day == 1
    assert d_from.month == 2
    assert d_to.day == 28
    assert d_to.month == 2
    assert time_str is None


def test_parse_russian_date_with_year():
    d_from, d_to, time_str = ConfigScraper._parse_date_range("с 21 ноября 2025 по 15 марта", "russian")
    assert d_from == datetime(2025, 11, 21)
    assert d_to.month == 3
    assert d_to.day == 15
    assert time_str is None


def test_parse_russian_date_po_only():
    d_from, d_to, time_str = ConfigScraper._parse_date_range("по 6 марта", "russian")
    assert d_from is None
    assert d_to.month == 3
    assert d_to.day == 6
    assert time_str is None


def test_parse_russian_date_with_time():
    d_from, d_to, time_str = ConfigScraper._parse_date_range("21 февраля, 19:00", "russian")
    assert d_from.month == 2
    assert d_from.day == 21
    assert d_to is None
    assert time_str == "19:00"


#######################################
## default time and time from detail page
#######################################
def test_config_default_time_when_no_time_on_site(monkeypatch):
    """Date without time — default to 19:00 instead of midnight."""
    def get(url, **kwargs):
        return Response(ok=True, text="<html><body></body></html>")

    monkeypatch.setattr(requests, "get", get)

    scraper = ConfigScraper()
    config = dict(TEST_SITE_CONFIG, date_format="russian", time_selector=None)
    event = scraper.get_event(
        event_url="https://testsite.example.com/afisha/no-time/",
        site=config,
        card_data={"url": "https://testsite.example.com/afisha/no-time/",
                   "title": "Событие без времени", "date_str": "12 июля"},
    )

    assert event.date_from.hour == 19
    assert event.date_from.minute == 0
    assert event.date_from == MSK.localize(
        datetime(event.date_from.year, 7, 12, 19, 0)
    )
    assert event.date_to == event.date_from + timedelta(hours=2)


def test_config_default_time_when_no_date(monkeypatch):
    """No date at all — fallback 'one week from now' also at 19:00."""
    def get(url, **kwargs):
        return Response(ok=True, text="<html><body></body></html>")

    monkeypatch.setattr(requests, "get", get)

    scraper = ConfigScraper()
    event = scraper.get_event(
        event_url="https://testsite.example.com/afisha/no-date/",
        site="testsite",
        card_data={"url": "https://testsite.example.com/afisha/no-date/",
                   "title": "Событие без даты"},
    )

    assert event.date_from.hour == 19
    assert event.date_from.minute == 0


def test_config_time_from_detail_page_sevcable_style(monkeypatch):
    """Time like 'с 20:30' from detail page (.infopage_time_val) is used."""
    def get(url, **kwargs):
        with open(TESTDATA / "event_page_sevcable.html") as f:
            return Response(ok=True, text=f.read())

    monkeypatch.setattr(requests, "get", get)

    scraper = ConfigScraper()
    event = scraper.get_event(
        event_url="https://sevcableport.ru/afisha/koncert-v-portu/",
        site="sevcable",
        card_data={"url": "https://sevcableport.ru/afisha/koncert-v-portu/",
                   "title": "Концерт в Порту", "date_str": "12 июля"},
    )

    assert event.date_from.hour == 20
    assert event.date_from.minute == 30
    assert event.date_from == MSK.localize(
        datetime(event.date_from.year, 7, 12, 20, 30)
    )
    assert "концерт у моря" in event.full_text


#######################################
## closing time and per-event place
#######################################
def test_config_date_to_from_closing_time(monkeypatch):
    """Range date + working hours 'с 12:00 до 22:00' on detail page."""
    html = """<html><body>
    <div class="infopage_time_val">с 12:00 до 22:00</div>
    <div class="descr">Выставка у моря.</div>
    </body></html>"""
    monkeypatch.setattr(requests, "get", lambda url, **kw: Response(ok=True, text=html))

    scraper = ConfigScraper()
    config = dict(
        TEST_SITE_CONFIG,
        date_format="russian",
        time_selector=".infopage_time_val",
        description_selector=".descr",
    )
    event = scraper.get_event(
        event_url="https://testsite.example.com/afisha/exhibition/",
        site=config,
        card_data={"url": "https://testsite.example.com/afisha/exhibition/",
                   "title": "Выставка", "date_str": "с 10 июля по 20 июля"},
    )

    year = event.date_from.year
    assert event.date_from == MSK.localize(datetime(year, 7, 10, 12, 0))
    assert event.date_to == MSK.localize(datetime(year, 7, 20, 22, 0))


def test_config_place_and_address_map():
    """Scraped place (scene) selects address from the 'places' map."""
    scraper = ConfigScraper()
    scraper._current_config = {
        "default_address": "пл. Островского, 6",
        "default_place": "Александринский театр",
        "places": {
            "Основная сцена": "пл. Островского, 6",
            "Новая сцена": "наб. реки Фонтанки, 49А",
        },
    }

    assert scraper._adress({"place": "Новая сцена"}) == "наб. реки Фонтанки, 49А"
    assert scraper._adress({"place": "Основная сцена"}) == "пл. Островского, 6"
    # Unknown place or no place — default address
    assert scraper._adress({"place": "Другая площадка"}) == "пл. Островского, 6"
    assert scraper._adress({}) == "пл. Островского, 6"

    assert scraper._place_name({"place": "Новая сцена"}) == "Александринский театр, Новая сцена"
    assert scraper._place_name({}) == "Александринский театр"
    # Markers and trailing punctuation are cleaned
    assert scraper._place_name({"place": "● Барная линия,"}) == "Александринский театр, Барная линия"


#######################################
## rusmuseum: default_category, default_time, places
#######################################
def test_config_rusmuseum_listing(monkeypatch):
    def get(url, **kwargs):
        with open(TESTDATA / "listing_rusmuseum.html") as f:
            return Response(ok=True, text=f.read())

    monkeypatch.setattr(requests, "get", get)

    scraper = ConfigScraper()
    events = list(scraper.get_events(request_params={"site": "rusmuseum"}))

    assert len(events) == 3
    by_title = {e.title[2:]: e for e in events}  # strip emoji prefix

    velikaya = by_title["Великая. Образ женщины в русском искусстве"]
    # Date range with years, default_time 10:00, end of last day
    assert velikaya.date_from == MSK.localize(datetime(2026, 6, 6, 10, 0))
    assert velikaya.date_to == MSK.localize(datetime(2027, 1, 11, 23, 59))
    # default_category for the site
    assert velikaya.category == "выставки"
    # Building from card → place and address
    assert velikaya.place_name == "Русский музей, Михайловский дворец"
    assert velikaya.adress == "Инженерная ул., 4"
    assert velikaya.url == (
        "https://rusmuseum.ru/exhibitions/current/"
        "velikaya-obraz-zhenshchiny-v-russkom-iskusstve/"
    )
    assert velikaya.poster_imag == "https://rusmuseum.ru/upload/iblock/109/velikaya.webp"
    assert "Русский музей открывает выставку" in velikaya.full_text

    shishkin = by_title["Иван Шишкин. Русский лес"]
    assert shishkin.place_name == "Русский музей, Корпус Бенуа"
    assert shishkin.adress == "наб. канала Грибоедова, 2"
    assert shishkin.date_from == MSK.localize(datetime(2026, 4, 25, 10, 0))

    tropinin = by_title["Василий Тропинин"]
    assert tropinin.place_name == "Русский музей, Мраморный дворец"
    assert tropinin.adress == "Миллионная ул., 5/1"
    assert tropinin.category == "выставки"


def test_config_erarta_listing(monkeypatch):
    def get(url, **kwargs):
        if url.rstrip("/").endswith("exhibitions"):
            filepath = TESTDATA / "listing_erarta.html"
        else:
            filepath = TESTDATA / "event_page_erarta.html"
        with open(filepath) as f:
            return Response(ok=True, text=f.read())

    monkeypatch.setattr(requests, "get", get)

    scraper = ConfigScraper()
    events = list(scraper.get_events(request_params={"site": "erarta"}))

    assert len(events) == 2
    event = events[0]

    assert event.title[2:] == "Нестор Хименес. Спектр синего шума"
    assert event.id == "CFG-ERAR-220925"
    assert event.category == "выставки"
    # Opening/closing hours from the site header "с 11:00 до 23:00"
    assert event.date_from == MSK.localize(datetime(2026, 4, 25, 11, 0))
    assert event.date_to == MSK.localize(datetime(2026, 8, 23, 23, 0))
    assert event.place_name == "Эрарта"
    assert event.adress == "29-я линия В.О., 2"
    assert event.url == "https://www.erarta.com/ru/calendar/exhibitions/detail/220925/"
    assert event.poster_imag == (
        "https://www.erarta.com/upload/resize_cache/iblock/357/370_240_2/khimenez.jpg"
    )
    # Description from the first .content block on the detail page
    assert "выставку мексиканского художника" in event.full_text


def test_config_philharmonia_listing(monkeypatch):
    requested = []

    def get(url, **kwargs):
        requested.append(url)
        if url.rstrip("/").endswith("afisha"):
            filepath = TESTDATA / "listing_philharmonia.html"
        elif "?year=" in url:
            return Response(ok=True, text="<html><body></body></html>")
        else:
            filepath = TESTDATA / "event_page_philharmonia.html"
        with open(filepath) as f:
            return Response(ok=True, text=f.read())

    monkeypatch.setattr(requests, "get", get)

    scraper = ConfigScraper()
    events = list(scraper.get_events(request_params={"site": "philharmonia"}))

    # Month pagination requested two future-month pages
    month_urls = [u for u in requested if "?year=" in u]
    assert len(month_urls) == 2

    assert len(events) == 2
    excursion, concert = events

    # Date split over spans with commas and weekday: "13 июля , 2026 12:00 , Пн"
    assert excursion.date_from == MSK.localize(datetime(2026, 7, 13, 12, 0))
    assert excursion.date_to == excursion.date_from + timedelta(hours=2)
    assert excursion.id == "CFG-PHIL-1101063"
    # Category detected from title keyword "экскурсия"
    assert excursion.category == "экскурсии"
    assert excursion.place_name == "Филармония им. Шостаковича, Большой зал"
    assert excursion.adress == "Михайловская ул., 2"
    # Price from the listing card
    assert excursion.price == "1000₽"
    # Description from the detail page
    assert "Продолжительность экскурсии" in excursion.full_text

    assert concert.date_from == MSK.localize(datetime(2026, 7, 20, 19, 0))
    assert concert.category == "концерты"
    assert concert.place_name == "Филармония им. Шостаковича, Малый зал"
    assert concert.adress == "Невский пр., 30"
    # Price range with a trailing "р."
    assert concert.price == "8000 — 10000₽"


#######################################
## dom.radio: require_date, card address, recurring events
#######################################
def test_config_domradio_listing(monkeypatch):
    def get(url, **kwargs):
        with open(TESTDATA / "listing_domradio.html") as f:
            return Response(ok=True, text=f.read())

    monkeypatch.setattr(requests, "get", get)

    scraper = ConfigScraper()
    events = list(scraper.get_events(request_params={"site": "domradio"}))

    # Open call (no date) and programme teaser ("ēlektron") are skipped
    assert len(events) == 2
    first, second = events

    year = first.date_from.year
    assert first.date_from == MSK.localize(datetime(year, 7, 15, 19, 0))
    assert second.date_from == MSK.localize(datetime(year, 7, 21, 19, 0))
    # Same title on different dates → different generated IDs
    assert first.id != second.id
    # Off-site address comes from the card, place stays default
    assert first.adress == "Набережная Адмиралтейского канала, 2"
    assert first.place_name == "Дом Радио"
    assert "Танцевальный вечер" in first.full_text


#######################################
## pagination
#######################################
def test_listing_page_urls_month_season():
    config = {
        "pagination": {
            "type": "month",
            "url_template": "?year={year}&month={month}",
            "months_ahead": 2,
            "season_start_month": 9,
        },
    }
    urls = ConfigScraper._listing_page_urls(config, "https://x.ru/afisha/")

    assert urls[0] == "https://x.ru/afisha/"
    assert len(urls) == 3
    now = datetime.now()
    year, month = now.year, now.month
    for url in urls[1:]:
        month += 1
        if month > 12:
            month, year = 1, year + 1
        expected_year = year - 1 if month < 9 else year
        assert url == f"https://x.ru/afisha/?year={expected_year}&month={month}"


def test_listing_page_urls_no_pagination():
    assert ConfigScraper._listing_page_urls({}, "https://x.ru/afisha/") == [
        "https://x.ru/afisha/"
    ]


def test_config_pagination_next_link(monkeypatch):
    page1 = """<html><body>
    <a class="event" href="/afisha/first/">
        <span class="event-name">First</span><span class="event-date">01.07.2026</span>
    </a>
    <a class="load-more" href="/afisha/?page=2">Загрузить еще</a>
    </body></html>"""
    page2 = """<html><body>
    <a class="event" href="/afisha/second/">
        <span class="event-name">Second</span><span class="event-date">02.07.2026</span>
    </a>
    </body></html>"""

    def get(url, **kwargs):
        return Response(ok=True, text=page2 if "page=2" in url else page1)

    monkeypatch.setattr(requests, "get", get)

    config = dict(
        TEST_SITE_CONFIG,
        skip_detail=True,
        card_description_selector=None,
        pagination={"type": "next", "next_selector": "a.load-more", "max_pages": 5},
    )
    scraper = ConfigScraper()
    events = list(scraper.get_events(request_params={"site": config}))

    assert [e.title[2:] for e in events] == ["First", "Second"]
    assert {e.id for e in events} == {"CFG-TEST-first", "CFG-TEST-second"}


def test_config_pagination_max_pages_guards_loop(monkeypatch):
    """A page linking to itself must not loop forever."""
    page = """<html><body>
    <a class="event" href="/afisha/only/">
        <span class="event-name">Only</span><span class="event-date">01.07.2026</span>
    </a>
    <a class="load-more" href="/afisha/">Еще</a>
    </body></html>"""

    monkeypatch.setattr(requests, "get", lambda url, **kw: Response(ok=True, text=page))

    config = dict(
        TEST_SITE_CONFIG,
        skip_detail=True,
        card_description_selector=None,
        pagination={"type": "next", "next_selector": "a.load-more", "max_pages": 5},
    )
    scraper = ConfigScraper()
    events = list(scraper.get_events(request_params={"site": config}))

    assert len(events) == 1


def test_config_default_category_not_used_when_detected():
    """Sites without default_category still detect from title/text."""
    scraper = ConfigScraper()
    scraper._current_config = {}
    assert scraper._category({"title": "Рок-концерт в клубе"}) == "концерты"

    scraper._current_config = {"default_category": "выставки"}
    # Explicit category from card wins over default
    assert scraper._category({"category": "театр", "title": "X"}) == "театр"
    assert scraper._category({"title": "Рок-концерт в клубе"}) == "выставки"


def test_detect_category():
    from escraper.parsers.utils import detect_category
    assert detect_category("Рок-концерт в клубе") == "концерты"
    assert detect_category("Выставка современного искусства") == "выставки"
    assert detect_category("Лекция о Маркесе") == "лекции"
    assert detect_category("Спектакль «Гамлет»") == "театр"
    assert detect_category("Кинопоказ и дискуссия") == "кино"
    assert detect_category("Что-то непонятное", "а в тексте есть мастер-класс") == "мастер-классы"
    assert detect_category("Просто название") == ""


#######################################
## config as dict in request_params
#######################################
def test_config_as_dict_in_get_events(requests_get_events):
    """Pass site config as dict instead of registered name."""
    scraper = ConfigScraper()
    params = {"site": TEST_SITE_CONFIG}
    events = list(scraper.get_events(request_params=params))

    assert len(events) == 3
    for e in events:
        assert e.source == "CFG"
        assert e.place_name == "Test Place"
        assert e.adress == "Test address, 1"


def test_config_as_dict_in_get_event(requests_get_event):
    """Pass site config as dict directly to get_event."""
    scraper = ConfigScraper()
    event_url = "https://testsite.example.com/afisha/concert-rock-2024/"
    card_data = {
        "url": event_url,
        "title": "Rock Concert 2024",
        "date_str": "15.06.2024",
        "image": "/upload/rock-concert.jpg",
    }

    event = scraper.get_event(event_url=event_url, site=TEST_SITE_CONFIG, card_data=card_data)

    assert event.source == "CFG"
    assert event.place_name == "Test Place"
    assert event.date_from.hour == 19
    assert event.date_from.minute == 30


def test_config_unknown_site_string():
    with pytest.raises(ValueError, match="Unknown site"):
        list(ConfigScraper().get_events(request_params={"site": "nonexistent"}))
