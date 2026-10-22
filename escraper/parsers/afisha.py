import json
import logging
import re
from datetime import datetime, timedelta

from .base import BaseParser, ALL_EVENT_TAGS
from .utils import strip_city
from ..emoji import add_emoji

logger = logging.getLogger(__name__)

NRP_MARKER = "window.__nrp = window.__nrp || {})['root'] = "

# Event type → category name (afisha's own section names).
TYPE_CATEGORIES = {
    "Concert": "Концерты",
    "Performance": "Театр",
    "Exhibition": "Выставки",
    "Excursion": "Экскурсии",
    "SportEvent": "Спорт",
}


def _extract_model(page_text):
    """Return the ``model`` dict of the page's ``__nrp`` state, or None."""
    start = page_text.find(NRP_MARKER)
    if start == -1:
        return None
    try:
        state, _ = json.JSONDecoder().raw_decode(page_text, start + len(NRP_MARKER))
    except json.JSONDecodeError:
        return None
    return state.get("model") if isinstance(state, dict) else None


def _parse_afisha_dt(date_str, offset="+03:00"):
    """Parse an afisha.ru local datetime (``"2026-12-19T19:00:00"`` plus the
    separate ``TimeZoneOffset``) to a Moscow-aware datetime."""
    if not date_str:
        return None
    dt = datetime.fromisoformat(date_str[:19] + (offset or "+03:00"))
    return dt.astimezone(BaseParser.TIMEZONE)


def _now():
    """Current Moscow time (a function so tests can freeze it)."""
    return datetime.now(BaseParser.TIMEZONE)


def _price_value(text):
    digits = re.sub(r"\D", "", str(text or "").split(",")[0].split(".")[0])
    return int(digits) if digits else None


class Afisha(BaseParser):
    """Parser for afisha.ru city listings (www.afisha.ru/{city}/schedule_*/)."""

    name = "afisha"
    BASE_URL = "https://www.afisha.ru"
    source = "AFISHA"
    REQUEST_DELAY = 1.0
    DEFAULT_REQUEST_TIMEOUT = 40
    DEFAULT_CITY = "spb"

    # Category → listing path under /{city}/. Genre slugs must be exact:
    # afisha.ru silently serves the whole listing for an unknown genre.
    CATEGORY_PATHS = {
        "concerts": "schedule_concert",
        "theatre": "schedule_theatre",
        "exhibitions": "schedule_exhibition",
        "standup": "schedule_concert/standup",
        "festivals": "schedule_concert/festivals",
        "musicals": "schedule_theatre/musicals",
        "party": "schedule_concert/vecherinki",
        "excursions": "schedule_excursion",
        "sports": "schedule_sport",
    }
    DEFAULT_CATEGORIES = [
        "concerts", "theatre", "exhibitions", "standup",
        "festivals", "musicals", "party",
    ]

    def __init__(self, use_proxy=True):
        super().__init__(use_proxy=use_proxy)
        self.event_url = None
        self._cities = {}  # slug → afisha city {"ID", "Name", "ShortName"}

    def resolve_city(self, city=None):
        """Return afisha's city record ``{"ID", "Name", "ShortName"}`` for a slug.

        Raises ValueError when afisha.ru has no such city (listing is 404).
        """
        slug = str(city or self.DEFAULT_CITY).strip().lower()
        if slug not in self._cities:
            model = self._fetch_listing(f"{self.BASE_URL}/{slug}/schedule_concert/", slug)
            if model is None:
                raise ValueError(f"AFISHA: can't resolve city {slug!r}: listing unavailable")
            self._cities[slug] = model["Context"]["RequestCity"]
        return self._cities[slug]

    def _fetch_listing(self, url, slug):
        """Fetch a listing page model; ValueError when the city does not exist."""
        response = self._request_get(url, return_on_status=(404,))
        if response is not None and response.status_code == 404:
            if slug not in self._cities:
                raise ValueError(f"AFISHA: unknown city {slug!r} ({url} is 404)")
            logger.warning("AFISHA: listing %s is 404, skipping", url)
            return None
        if not response:
            return None
        model = _extract_model(response.text)
        if model is None:
            logger.warning("AFISHA: no page state on %s", url)
            return None
        request_city = (model.get("Context") or {}).get("RequestCity")
        if request_city and slug not in self._cities:
            self._cities[slug] = request_city
        return model

    def get_event(self, event_url=None, tags=None, listing_hint=None, city=None,
                  date_from=None, date_to=None):
        """Fetch and parse a single afisha.ru event page.

        Parameters
        ----------
        event_url : str
            Full URL of the event page, e.g.
            https://www.afisha.ru/concert/maksim-6055070/
        tags : list, optional
            Event tags to return. Defaults to ALL_EVENT_TAGS.
        listing_hint : dict, optional
            The listing tile of the event (``ScheduleWidget.Items[].Tile``);
            supplies venue and dates for events without sessions (exhibitions).
        city : str, optional
            afisha city slug (spb, msk, kazan, ...). Defaults to spb. The
            event's session, venue and address are taken for this city.
        date_from, date_to : datetime, optional
            Take the first session of the city inside this window.

        Raises ValueError when the page has no event data or the event has no
        session in the city (inside the window).
        """
        if event_url is None:
            raise ValueError("'event_url' required.")

        city_info = self.resolve_city(city)
        response = self._request_get(
            event_url, cookies={"HomeGeographyPlaceID": str(city_info["ID"])}
        )
        if not response:
            raise ValueError(f"Can't fetch event page {event_url}")

        model = _extract_model(response.text)
        if model is None:
            raise ValueError("Can't find event data on page")

        self.event_url = event_url
        event_data = self._normalize(model, city_info, listing_hint or {}, date_from, date_to)
        event_data["description"] = self._extract_description(response.text)
        if event_data["date_from"] is None:
            raise ValueError(
                f"no session in {city_info['Name']} for the requested dates"
            )
        return self.parse(event_data, tags=tags or ALL_EVENT_TAGS)

    def _normalize(self, model, city_info, hint, date_from=None, date_to=None):
        info = next(
            (v for k, v in model.items()
             if k.endswith("Info") and k not in ("ScheduleInfo", "PlaceInfo")
             and isinstance(v, dict) and v.get("Name")),
            None,
        )
        if info is None:
            raise ValueError("Can't find event info in page data")

        schedule_info = model.get("ScheduleInfo") or hint.get("ScheduleInfo") or {}
        now = _now()
        lower = max(date_from, now) if date_from else now

        place_name, address, price = "", "", None
        start = end = None
        has_tickets = schedule_info.get("HasTickets")

        schedule = model.get("Schedule")
        if isinstance(schedule, list):
            # Sessions: concerts, performances, ... — pick the city's first one.
            sessions = []
            for entry in schedule:
                place = entry.get("Place") or {}
                if (place.get("City") or {}).get("ShortName") != city_info["ShortName"]:
                    continue
                for session in entry.get("Sessions") or []:
                    dt = _parse_afisha_dt(session.get("DateTime"), session.get("TimeZoneOffset"))
                    if dt is None or dt < lower or (date_to and dt >= date_to):
                        continue
                    sessions.append((dt, place, session))
            if sessions:
                start, place, session = min(sessions, key=lambda s: s[0])
                end = start + timedelta(hours=3)
                place_name = place.get("Name") or ""
                address = place.get("Address") or ""
                # ScheduleInfo covers every city of a tour: use the session's own data.
                price = _price_value(session.get("MinPriceFormatted"))
                has_tickets = bool(price) or bool(session.get("FreeEntry"))
        else:
            # No sessions (exhibitions): a date range at one venue.
            place = (
                model.get("PlaceInfoModel") or model.get("PlaceInfo")
                or (hint.get("Notice") or {}).get("Place") or {}
            )
            place_name = place.get("Name") or ""
            address = place.get("Address") or ""
            offset = schedule_info.get("TimeZoneOffset")
            range_start = _parse_afisha_dt(schedule_info.get("MinScheduleDate"), offset)
            range_end = _parse_afisha_dt(schedule_info.get("MaxScheduleDate"), offset)
            # MaxScheduleDate is the last open day (00:00): open until its end.
            closes = range_end + timedelta(days=1) if range_end is not None else None
            overlaps = (
                range_start is not None
                and (closes is None or closes > lower)
                and (date_to is None or range_start < date_to)
            )
            if overlaps:
                # First open day inside the window, not the opening day years ago.
                first_day = lower.replace(hour=0, minute=0, second=0, microsecond=0)
                start, end = max(range_start, first_day), range_end
            if schedule_info.get("MinPrice"):
                price = int(schedule_info["MinPrice"])

        return {
            "info": info,
            "media": model.get("Media") or {},
            "hint": hint,
            "category": TYPE_CATEGORIES.get(info.get("Type"), ""),
            "date_from": start,
            "date_to": end,
            "place_name": place_name,
            "address": strip_city(address, city_info["Name"]),
            "price": price,
            "has_tickets": has_tickets,
        }

    def get_events(self, request_params=None, tags=None, existed_event_ids=None):
        """Scrape events from afisha.ru city listings.

        Parameters
        ----------
        request_params : dict
            city : str, default "spb"
                afisha city slug: spb, msk, kazan, ekaterinburg, ...
                ValueError if afisha.ru has no such city.

            categories : list of str
                Keys of CATEGORY_PATHS. Defaults to DEFAULT_CATEGORIES.

            date_from : str 'YYYY-MM-DD', optional
                Keep events with a session on/after this date.
            date_to : str 'YYYY-MM-DD', optional (inclusive)
            days : int, optional
                Window length from date_from when date_to is absent.
                With a full window the per-day listings are scanned.

            max_pages : int
                Listing pages per category (per day with a date window).
                Default 1 without a window, 10 with one.

        tags : list, optional
            Event tags to return. Defaults to ALL_EVENT_TAGS.

        existed_event_ids : list
            Event IDs to skip, e.g. ["AFISHA-6055070"].

        Examples
        --------
        >>> afisha = Afisha()
        >>> list(afisha.get_events(request_params={
        ...     "city": "kazan",
        ...     "categories": ["concerts"],
        ...     "date_from": "2026-11-01",
        ...     "days": 3,
        ... }))  # doctest: +SKIP

        Yields parsed events one at a time as event pages are scraped (generator).
        """
        request_params = request_params or {}
        existed_event_ids = list(existed_event_ids) if existed_event_ids else []

        city = str(request_params.get("city") or self.DEFAULT_CITY).strip().lower()
        categories = request_params.get("categories", self.DEFAULT_CATEGORIES)

        date_from = date_to = None
        if "date_from" in request_params:
            date_from = self.TIMEZONE.localize(
                datetime.strptime(request_params["date_from"], "%Y-%m-%d")
            )
            if "date_to" in request_params:
                date_to = self.TIMEZONE.localize(
                    datetime.strptime(request_params["date_to"], "%Y-%m-%d")
                ) + timedelta(days=1)
            elif "days" in request_params:
                date_to = date_from + timedelta(days=int(request_params["days"]))

        by_day = date_from is not None and date_to is not None
        max_pages = int(request_params.get("max_pages", 10 if by_day else 1))

        self.resolve_city(city)
        seen_urls = set()  # a tile repeats on every day it plays: fetch it once

        for category in categories:
            path = self.CATEGORY_PATHS.get(category)
            if path is None:
                logger.warning("AFISHA: unsupported category %r, skipping", category)
                continue

            for tile in self._iter_tiles(city, path, date_from, date_to, by_day, max_pages):
                if tile.get("IsItemFromAnotherCity") or not tile.get("Url"):
                    continue
                event_url = self.BASE_URL + tile["Url"].split("#")[0].split("?")[0]
                event_id = self._id_from_url(event_url)
                if event_id in existed_event_ids or event_url in seen_urls:
                    continue
                seen_urls.add(event_url)

                try:
                    event = self.get_event(
                        event_url=event_url, tags=tags, listing_hint=tile, city=city,
                        date_from=date_from, date_to=date_to,
                    )
                except (ValueError, KeyError, TypeError) as e:
                    logger.info("AFISHA: skipping event %s: %s", event_url, e)
                    continue

                existed_event_ids.append(event_id)
                yield event

    def _iter_tiles(self, city, path, date_from, date_to, by_day, max_pages):
        """Yield listing tiles of a category, page by page (per day with a window)."""
        first_url = f"{self.BASE_URL}/{city}/{path}/"
        model = self._fetch_listing(first_url, city)
        if model is None:
            return

        genre = path.split("/")[1] if "/" in path else None
        filter_menu = (model.get("ScheduleWidget") or {}).get("FilterMenu") or {}
        if genre:
            selected = [
                item.get("Value")
                for item in (filter_menu.get("Genres") or {}).get("Items") or []
                if item.get("Selected")
            ]
            if genre not in selected:
                # afisha.ru serves the whole listing for a genre it doesn't know.
                logger.warning("AFISHA: genre %r not available on %s, skipping", genre, first_url)
                return

        if by_day:
            start_urls = []
            for day in (filter_menu.get("Calendar") or {}).get("AvailableDays") or []:
                day_date = self.TIMEZONE.localize(datetime.fromisoformat(day["Value"][:19]))
                if date_from <= day_date < date_to:
                    # Calendar links drop the genre: rebuild them under our path.
                    day_slug = day["Url"].rstrip("/").split("/")[-1]
                    start_urls.append(f"{first_url}{day_slug}/")
        else:
            start_urls = [first_url]

        for start_url in start_urls:
            page_model = model if start_url == first_url else None
            for page in range(1, max_pages + 1):
                if page_model is None:
                    url = start_url if page == 1 else f"{start_url}page{page}/"
                    page_model = self._fetch_listing(url, city)
                    if page_model is None:
                        break
                widget = page_model.get("ScheduleWidget") or {}
                for item in widget.get("Items") or []:
                    if item.get("Tile"):
                        yield item["Tile"]
                if page >= (widget.get("Pager") or {}).get("PagesCount", 1):
                    break
                page_model = None

    def _id_from_url(self, event_url):
        match = re.search(r"-(\d+)/?(?:[?#].*)?$", event_url)
        event_id = match.group(1) if match else event_url.rstrip("/").split("/")[-1]
        return f"{self.source}-{event_id}"

    def _adress(self, event_data):
        return event_data.get("address", "")

    def _category(self, event_data):
        return event_data.get("category") or ""

    def _date_from(self, event_data):
        self._date_from_ = event_data.get("date_from")
        return self._date_from_

    def _date_to(self, event_data):
        self._date_to_ = event_data.get("date_to")
        return self._date_to_

    def _date_from_to(self, event_data):
        return f"{self._date_from_} – {self._date_to_}"

    def _id(self, event_data):
        return self._id_from_url(self.event_url)

    def _place_name(self, event_data):
        return event_data.get("place_name", "")

    @staticmethod
    def _extract_description(page_text):
        """Return the plain-text event description from the page DOM (may be '')."""
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(page_text, "lxml")
        el = soup.select_one(
            '[data-test="OBJECT-DESCRIPTION-CONTENT"] [data-test="RESTRICT-TEXT"]'
        )
        if el is None:
            return ""
        return el.get_text("\n", strip=True)

    def _full_text(self, event_data):
        if event_data.get("description"):
            return event_data["description"]
        # Fallback: the model's description (often an SEO text).
        html = event_data["info"].get("Description") or ""
        if not html:
            return ""
        html = re.sub(r"<(?:p|br|h\d)[^>]*>", "\n", html)
        text = self.remove_html_tags(html).replace("\r", "")
        return re.sub(r"\n\s*\n+", "\n", text).strip()

    def _post_text(self, event_data):
        return self.prepare_post_text(self._full_text(event_data))

    def _poster_imag(self, event_data):
        for source in (event_data["media"], event_data["hint"]):
            for key in ("Photo16x9", "Image16x9", "Photo1x1", "Image1x1"):
                image = source.get(key) or {}
                if image.get("Url"):
                    return image["Url"]
        return None

    def _price(self, event_data):
        price = event_data.get("price")
        if price:
            return str(int(price)) + "₽"
        return "на сайте"

    def _title(self, event_data):
        return add_emoji(event_data["info"]["Name"].strip())

    def _url(self, event_data):
        if self.event_url:
            return self.event_url
        return self.BASE_URL + event_data["info"].get("Url", "")

    def _ticket_url(self, event_data):
        return self._url(event_data)

    def _source(self, event_data):
        return self.source

    def _is_registration_open(self, event_data):
        return bool(event_data.get("has_tickets"))
