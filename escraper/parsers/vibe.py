import base64
import json
import logging
import os
import re
import time
from datetime import datetime

from bs4 import BeautifulSoup

from .base import BaseParser, ALL_EVENT_TAGS
from .ticketscloud import extract_tc_event
from ..emoji import add_emoji

logger = logging.getLogger(__name__)

# GeoNames ids used by Vibe as city_id (full list: GET /api/customers/v2/feed/cities)
CITY_NAMES = {
    "498817": "Санкт-Петербург",
    "524901": "Москва",
    "551487": "Казань",
}

# Vibe `system_` -> our event id prefix. TC keeps "TC" so ids match the Ticketscloud parser.
SYSTEM_SOURCES = {
    "TC": "TC",
    "TICKETLAND": "TL",
}

PLACEHOLDER_MEDIA = "/images/categories/"


def partner_from_token(token):
    """Partner id from the TC_TOKEN JWT payload ({"partner": "<id>"}), or None."""
    if not token:
        return None
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(payload)).get("partner")
    except (IndexError, ValueError):
        return None


class Vibe(BaseParser):
    """
    City-wide event feed of Vibe (vibeapp.ru), the consumer app of Ticketscloud.

    The feed lists every TC organizer of the city (no org_ids list needed) plus
    Ticketland. TC events are enriched from the event page on our partner
    subdomain (`https://<partner>.ticketscloud.org/e/<external_id>`), which opens
    any TC event regardless of organizer. Ticketland events (opt-in) are built
    from feed data only — ticketland.ru itself is behind an anti-bot challenge.
    """
    name = "Vibe"
    API_URL = "https://app.vibeapp.ru/api/customers/v2"
    WEB_URL = "https://web.vibeapp.ru"
    HEADERS = {
        "X-Application": "kryptonite",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    }
    PAGE_LIMIT = 50
    REQUEST_DELAY = 1.0
    source = "TC"

    def __init__(self, use_proxy=True):
        super().__init__(use_proxy=use_proxy)
        self.TC_TOKEN = os.getenv('TC_TOKEN')
        self.TC_VIBE_REF = os.getenv('TC_VIBE_REF')
        self.partner = partner_from_token(self.TC_TOKEN)
        self.city = CITY_NAMES["498817"]
        self.vibe_event = {}
        self.tc_event = None

    def get_event(self, event_id=None, tags=None):
        """
        Parameters:
        -----------
        event_id : str
            Vibe internal event id (`data.id` in the feed, also in web.vibeapp.ru/events/<id>)
        """
        if event_id is None:
            raise ValueError("'event_id' required.")

        response = self._request_get(f"{self.API_URL}/events/{event_id}", headers=self.HEADERS)
        if response is None:
            return None
        return self._build_event(response.json(), tags or ALL_EVENT_TAGS)

    def get_events(self, request_params=None, tags=None, existed_event_ids=None):
        """
        Parameters:
        -----------
        request_params : dict, default None
            city_id : str, default '498817' (Санкт-Петербург)
                GeoNames id: Москва '524901', Казань '551487'
            days : int, default 7
                window from now for event start
            systems : list, default ['TC']
                Vibe systems to keep: 'TC', 'TICKETLAND'
            exclude_categories : list, default []
                Vibe categories to skip, e.g. ['Детям']
            partner_subdomain : str, default partner id from TC_TOKEN
                subdomain used to open TC event pages
            enrich : bool, default True
                fetch TC event page for org id, cover and widget link
            max_pages : int, default 100
                feed pages of 50 events

        tags : list of tags, default all available event tags

        existed_event_ids : list of event IDs to skip (TC-<id>, TL-<id>)

        Examples:
        ----------
        >>> vibe = Vibe()
        >>> list(vibe.get_events(request_params={"city_id": "498817", "days": 7}))  # doctest: +SKIP
        """
        request_params = request_params or {}
        existed_event_ids = set(existed_event_ids) if existed_event_ids else set()
        tags = tags or ALL_EVENT_TAGS

        city_id = str(request_params.get("city_id", "498817"))
        days = int(request_params.get("days", 7))
        systems = set(request_params.get("systems", ["TC"]))
        exclude_categories = set(request_params.get("exclude_categories", []))
        self.partner = request_params.get("partner_subdomain", self.partner)
        self.enrich = request_params.get("enrich", True)
        max_pages = int(request_params.get("max_pages", 100))
        self.city = request_params.get("city", CITY_NAMES.get(city_id, ""))

        now = int(time.time())
        where = json.dumps({"city_id": city_id, "start": {"$between": [now, now + days * 86400]}})

        for page in range(max_pages):
            params = dict(where=where, limit=self.PAGE_LIMIT, offset=page * self.PAGE_LIMIT, sort="rating")
            response = self._request_get(f"{self.API_URL}/feed", params=params, headers=self.HEADERS)
            if response is None:
                logger.warning("VIBE: feed request failed on page %d (city %s), stopping", page, city_id)
                break
            try:
                items = response.json()
            except ValueError as e:
                logger.warning("VIBE: invalid feed JSON on page %d (city %s): %s", page, city_id, e)
                break
            if not items:
                break

            for item in items:
                data = item.get("data") or {}
                if item.get("type") != "event" or data.get("system_") not in systems:
                    continue
                # the feed also returns events of nearby towns
                if str(data.get("city")) != city_id or data.get("category") in exclude_categories:
                    continue

                event_id = self._make_id(data)
                if event_id in existed_event_ids:
                    continue
                existed_event_ids.add(event_id)

                event = self._build_event(data, tags)
                if event is not None:
                    yield event

    def _build_event(self, data, tags):
        self.vibe_event = data
        self.source = SYSTEM_SOURCES.get(data.get("system_"), data.get("system_") or "VIBE")
        self.tc_event = None
        if self.source == "TC" and getattr(self, "enrich", True) and self.partner:
            self.tc_event = self._fetch_tc_event(data["external_id"])
        try:
            return self.parse(data, tags=tags)
        except (KeyError, TypeError, ValueError) as e:
            logger.warning("VIBE: failed to parse event %s (%s): %s", data.get("id"), data.get("name"), e)
            return None

    def _fetch_tc_event(self, external_id):
        url = self._tc_page_url(external_id)
        response = self._request_get(url)
        if response is None:
            logger.warning("VIBE: TC page unavailable for %s, using feed data only", url)
            return None
        try:
            tc_event = extract_tc_event(BeautifulSoup(response.text, "lxml"))
        except ValueError as e:
            logger.warning("VIBE: bad tc_event JSON on %s: %s", url, e)
            return None
        if tc_event is None:
            logger.warning("VIBE: no tc_event on %s, using feed data only", url)
        return tc_event

    def _tc_page_url(self, external_id):
        return f"https://{self.partner}.ticketscloud.org/e/{external_id}"

    def _make_id(self, data):
        source = SYSTEM_SOURCES.get(data.get("system_"), data.get("system_") or "VIBE")
        return f"{source}-{data['external_id']}"

    def _strip_city(self, text):
        if not text or not self.city:
            return text
        text = re.sub(rf"^(г\.?\s*)?{re.escape(self.city)},\s*", "", text.strip())
        return re.sub(rf",\s*(г\.?\s*)?{re.escape(self.city)}$", "", text)

    def _adress(self, data):
        address = (data.get("venue") or {}).get("address")
        if address and "онлайн" in address.lower():
            return "Онлайн"
        return self._strip_city(address)

    def _category(self, data):
        return data.get("category")

    def _date_from(self, data):
        return datetime.fromtimestamp(data["start"], self.TIMEZONE)

    def _date_to(self, data):
        end = data.get("end")
        # Ticketland events come with a placeholder end = start + 24h
        if not end or (data.get("system_") == "TICKETLAND" and end - data["start"] == 86400):
            return self._date_from(data)
        return datetime.fromtimestamp(end, self.TIMEZONE)

    def _date_from_to(self, data):
        date_from, date_to = self._date_from(data), self._date_to(data)
        if date_to.date() != date_from.date():
            return f"{date_from:%d.%m.%Y %H:%M} – {date_to:%d.%m.%Y}"
        return f"{date_from:%d.%m.%Y %H:%M}"

    def _id(self, data):
        return self._make_id(data)

    def _place_name(self, data):
        return self._strip_city((data.get("venue") or {}).get("name"))

    def _full_text(self, data):
        description = data.get("description") or ""
        text = BeautifulSoup(description, "lxml").get_text("\n")
        return re.sub(r"\n\s*\n+", "\n\n", text).strip()

    def _post_text(self, data):
        return self.prepare_post_text(self._full_text(data))

    def _poster_imag(self, data):
        if self.tc_event and "cover_original" in (self.tc_event.get("media") or {}):
            return self.tc_event["media"]["cover_original"]["url"]
        media = data.get("media")
        if not media or PLACEHOLDER_MEDIA in media:
            return None
        return media

    def _price(self, data):
        price_min = data.get("price_min")  # kopecks
        if not price_min:
            return "на сайте"
        return f"{price_min // 100}₽"

    def _title(self, data):
        return add_emoji(data["name"].strip())

    def _url(self, data):
        if self.source == "TC" and self.partner:
            return self._tc_page_url(data["external_id"])
        return f"{self.WEB_URL}/events/{data['id']}"

    def _ticket_url(self, data):
        if self.source == "TC" and self.TC_TOKEN and self.tc_event:
            return (f"https://ticketscloud.com/v1/widgets/common?token={self.TC_TOKEN}"
                    f"&event={data['external_id']}&org={self._org_id(data)}&vibe_ref={self.TC_VIBE_REF}")
        return self._url(data)

    def _source(self, data):
        return self.source

    def _org_id(self, data):
        """TC organizer id (also its ticketscloud.org subdomain); None without the TC page."""
        if self.tc_event:
            return self.tc_event["org"]["id"]
        return None

    def _org_name(self, data):
        if self.tc_event:
            return self.tc_event["org"].get("name")
        return data.get("org_name")

    def _is_registration_open(self, data):
        if self.tc_event and "tickets_amount_vacant" in self.tc_event:
            return self.tc_event["tickets_amount_vacant"] > 0
        return (data.get("amount_vacant") or 0) > 0
