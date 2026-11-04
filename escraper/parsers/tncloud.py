"""Parser for museum box offices on the TN-Cloud ticketing engine.

The engine serves the whole catalogue in one request: ``GET {base}/api/afisha``
→ products (``action``), sessions (``calendar``), venues, menus. Prices come
from ``POST {base}/api/no-scheme`` with ``{"hash": <hash_id>}``. Neither call
needs cookies, a referer or a CSRF token.

What it is good for: dated programmes — lectures, master classes, kids'
classes, shows — with exact session times and prices.

What it deliberately skips (per-site ``kinds``):
  * entry tickets / exhibitions — the calendar only covers the sale horizon
    (4–8 weeks), not the exhibition period, and one exhibition has 5–8 ticket
    variants; exhibitions come from the venue sites (ConfigScraper) instead;
  * subscriptions, bus excursions, complex tickets.
"""

import json
import logging
import os
import re
from collections import defaultdict
from datetime import datetime, timedelta

import requests
from bs4 import BeautifulSoup

from .base import BaseParser, ALL_EVENT_TAGS
from .utils import detect_category
from ..emoji import add_emoji

logger = logging.getLogger(__name__)


# site name → engine instance. "kinds": menukind_id values to take (see the
# kind_menu of /api/afisha); everything else is skipped.
SITES = {
    "kremlin": {
        "code": "KREM",
        "city": "kazan",
        "base_url": "https://tickets.kazan-kremlin.ru",
        # 1 входные билеты, 2 абонементы, 3 экскурсии, 5 программы
        "kinds": {"5"},
        "default_place": "Казанский Кремль",
        "default_address": "территория Кремль",
    },
    "rusmuseum": {
        "code": "RUSM",
        "city": "spb",
        "base_url": "https://ticket.rusmuseum.ru",
        # 5 мероприятия и арт-медиации, 6 лекции, 7 детям, 29 новогодние ёлки.
        # Skipped: 1 входные, 2 абонементы, 3 экскурсии, 11 комплексные,
        # 23 многодетным, 18/33/129/130 — per-exhibition ticket menus.
        "kinds": {"5", "6", "7", "29"},
        "default_place": "Русский музей",
        "default_address": "Инженерная ул., 4",
        # /api/no-scheme answers {"action": false} + Oracle warnings here
        "prices": False,
    },
}

DEFAULT_TIME = (10, 0)        # session without a time: museums open at 10
DEFAULT_DURATION_MIN = 120    # session without a duration


class TNCloud(BaseParser):
    name = "tncloud"
    source = "TNC"
    REQUEST_DELAY = 0.5

    def __init__(self, use_proxy=True):
        super().__init__(use_proxy=use_proxy)
        self._site = None
        self._afisha_cache = {}

    # ------------------------------------------------------------------ API
    @staticmethod
    def _resolve_site(site):
        if isinstance(site, dict):
            return site
        if isinstance(site, str) and site in SITES:
            return SITES[site]
        raise ValueError(f"TNC: unknown site {site!r}; known: {', '.join(sorted(SITES))}")

    def _load_afisha(self, site):
        base = site["base_url"]
        if base in self._afisha_cache:
            return self._afisha_cache[base]
        url = f"{base}/api/afisha"
        response = self._request_get(url, headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json, text/plain, */*",
        })
        if not response:
            logger.error("TNC-%s: can't load %s", site["code"], url)
            return None
        try:
            data = response.json()["response"]
        except (ValueError, KeyError, TypeError) as e:
            logger.error("TNC-%s: bad afisha JSON from %s: %s", site["code"], url, e)
            return None
        self._afisha_cache[base] = data
        return data

    def _request_post_json(self, url, payload):
        """POST with JSON body; returns parsed JSON or None. One retry."""
        kwargs = {"json": payload, "timeout": self.DEFAULT_REQUEST_TIMEOUT,
                  "headers": {"User-Agent": "Mozilla/5.0",
                              "X-Requested-With": "XMLHttpRequest"}}
        if self.use_proxy and "PROXY" in os.environ:
            kwargs["proxies"] = {"http": os.environ["PROXY"], "https": os.environ["PROXY"]}
        for attempt in range(2):
            try:
                response = requests.post(url, **kwargs)
                if response.ok:
                    # Some instances append PHP warnings after the JSON body
                    text = response.text if isinstance(response.text, str) else ""
                    if text:
                        return json.JSONDecoder().raw_decode(text.lstrip())[0]
                    return response.json()
                logger.warning("TNC: POST %s → %s (attempt %d)", url, response.status_code, attempt + 1)
            except (requests.RequestException, ValueError) as e:
                logger.warning("TNC: POST %s failed (attempt %d): %s", url, attempt + 1, e)
        return None

    def _fetch_prices(self, site, hash_id, day):
        """Prices of the first session day: sorted unique non-zero values."""
        data = self._request_post_json(f"{site['base_url']}/api/no-scheme", {"hash": hash_id})
        prices = ((data or {}).get("response") or {}).get("price") or []
        values = set()
        free = False
        for p in prices:
            if day and p.get("action_day") and p["action_day"] != day:
                continue
            try:
                value = int(float(p.get("price") or 0))
            except ValueError:
                continue
            if value > 0:
                values.add(value)
            else:
                free = True
        if values:
            return sorted(values)
        return [0] if free else None

    # -------------------------------------------------------------- helpers
    def _now(self):
        """Naive Moscow 'now' (overridden in tests)."""
        return datetime.now(self.TIMEZONE).replace(tzinfo=None)

    @staticmethod
    def _sessions(calendar_rows, now):
        """Upcoming sessions as sorted [(datetime, duration_min, tickets)]."""
        sessions = []
        for row in calendar_rows:
            if not row.get("eventday"):
                continue
            try:
                day = datetime.strptime(row["eventday"], "%d.%m.%Y")
            except ValueError:
                continue
            hour, minute = DEFAULT_TIME
            if row.get("eventtime"):
                match = re.match(r"(\d{1,2}):(\d{2})", row["eventtime"])
                if match:
                    hour, minute = int(match.group(1)), int(match.group(2))
            start = day.replace(hour=hour, minute=minute)
            if start.date() < now.date():
                continue
            try:
                duration = int(row.get("eventduration") or 0) or DEFAULT_DURATION_MIN
            except ValueError:
                duration = DEFAULT_DURATION_MIN
            try:
                tickets = int(row.get("ticketcount") or 0)
            except ValueError:
                tickets = 0
            sessions.append((start, duration, tickets))
        return sorted(sessions)

    @staticmethod
    def _clean_text(html):
        if not html:
            return ""
        soup = BeautifulSoup(html, "lxml")
        for br in soup.find_all("br"):
            br.replace_with("\n")
        text = soup.get_text()
        text = re.sub(r"[ \t\r\f\v]+", " ", text)
        text = re.sub(r"\n\s*\n+", "\n", text)
        return text.strip()

    @staticmethod
    def _clean_venue(name):
        # " 5.1 Центр «Эрмитаж-Казань» Основная экспозиция" → "Центр «Эрмитаж-Казань» …"
        return re.sub(r"^\s*[\d.]+\s+", "", name or "").strip()

    def _build_event(self, site, action, sessions, venues, kind_names, with_prices):
        venue = venues.get(action.get("seatroot_id")) or {}
        first_day = sessions[0][0].strftime("%d.%m.%Y")
        prices = None
        if with_prices and action.get("hash_id"):
            prices = self._fetch_prices(site, action["hash_id"], first_day)
        return {
            "site": site,
            "action": action,
            "sessions": sessions,
            "venue": venue,
            "kind_name": kind_names.get(action.get("menukind_id"), ""),
            "prices": prices,
        }

    # ------------------------------------------------------------ interface
    def get_event(self, hash_id=None, site=None, tags=None, with_prices=None):
        """One product by its hash_id (the /event/<HASH> part of the ticket URL)."""
        if hash_id is None:
            raise ValueError("'hash_id' required.")
        if site is None:
            raise ValueError("'site' required.")
        site = self._resolve_site(site)
        if with_prices is None:
            with_prices = site.get("prices", True)
        data = self._load_afisha(site)
        if not data:
            return None
        action = next((a for a in data.get("action") or [] if a.get("hash_id") == hash_id), None)
        if action is None:
            raise ValueError(f"TNC-{site['code']}: no event with hash {hash_id}")
        now = self._now()
        rows = [c for c in data.get("calendar") or [] if c.get("event_id") == action["event_id"]]
        sessions = self._sessions(rows, now)
        if not sessions:
            return None
        venues = {v.get("seatroot_id"): v for v in data.get("venues") or []}
        kinds = {k.get("menukind_id"): k.get("menukindname_ru", "") for k in data.get("kind_menu") or []}
        event = self._build_event(site, action, sessions, venues, kinds, with_prices)
        self._site = site
        return self.parse(event, tags=tags or ALL_EVENT_TAGS)

    def get_events(self, request_params=None, tags=None, existed_event_ids=None):
        """Upcoming dated programmes of one TN-Cloud box office.

        Parameters
        ----------
        request_params : dict
            site : str or dict
                Registered site name ("kremlin", "rusmuseum") or a config dict
                with code, city, base_url, kinds, default_place, default_address.
            kinds : iterable of str, optional
                Override the site's menukind_id filter.
            with_prices : bool, default: site's "prices" (True)
                One POST /api/no-scheme per event for prices.
        tags : list, optional
        existed_event_ids : list, optional
            Event ids to skip (no price request is made for them).
        """
        request_params = request_params or {}
        tags = tags or ALL_EVENT_TAGS
        existed = set(existed_event_ids) if existed_event_ids else set()

        site_param = request_params.get("site")
        if site_param is None:
            raise ValueError("'site' required in request_params.")
        site = self._resolve_site(site_param)
        kinds = {str(k) for k in request_params.get("kinds") or site.get("kinds") or ()}
        with_prices = request_params.get("with_prices", site.get("prices", True))

        data = self._load_afisha(site)
        if not data:
            return

        calendar = defaultdict(list)
        for row in data.get("calendar") or []:
            calendar[row.get("event_id")].append(row)
        venues = {v.get("seatroot_id"): v for v in data.get("venues") or []}
        kind_names = {k.get("menukind_id"): k.get("menukindname_ru", "")
                      for k in data.get("kind_menu") or []}
        now = self._now()

        self._site = site
        seen = set()
        for action in data.get("action") or []:
            if kinds and action.get("menukind_id") not in kinds:
                continue
            event_id = f"{self.source}-{site['code']}-{action.get('event_id')}"
            if event_id in existed or event_id in seen:
                continue
            seen.add(event_id)

            sessions = self._sessions(calendar.get(action.get("event_id"), []), now)
            if not sessions:
                continue

            try:
                event = self._build_event(site, action, sessions, venues, kind_names, with_prices)
                yield self.parse(event, tags=tags)
            except Exception as e:  # one broken product must not stop the feed
                logger.warning("TNC-%s: skip event %s (%s): %s",
                               site["code"], action.get("event_id"), action.get("hash_id"), e)

    # --------------------------------------------------------------- fields
    def _title(self, event_data):
        title = re.sub(r"\s+", " ", self._clean_text(event_data["action"].get("event_ru"))).strip()
        return add_emoji(title)

    def _full_text(self, event_data):
        return self._clean_text(event_data["action"].get("descript_ru"))

    def _post_text(self, event_data):
        return self.prepare_post_text(self._full_text(event_data))

    def _id(self, event_data):
        site = event_data["site"]
        return f"{self.source}-{site['code']}-{event_data['action'].get('event_id')}"

    def _url(self, event_data):
        site = event_data["site"]
        return f"{site['base_url']}/event/{event_data['action'].get('hash_id')}"

    def _ticket_url(self, event_data):
        first = event_data["sessions"][0][0]
        return f"{self._url(event_data)}/{first.strftime('%Y-%m-%d')}"

    def _date_from(self, event_data):
        return self.TIMEZONE.localize(event_data["sessions"][0][0])

    def _date_to(self, event_data):
        start, duration, _ = event_data["sessions"][-1]
        return self.TIMEZONE.localize(start + timedelta(minutes=duration))

    def _date_from_to(self, event_data):
        sessions = event_data["sessions"]
        date_from = self._date_from(event_data)
        date_to = self._date_to(event_data)
        if date_from.date() != date_to.date():
            return f"{date_from:%d.%m.%Y} – {date_to:%d.%m.%Y}"
        if len(sessions) > 1:
            # Several sessions in one day: "17.11.2026 11:00, 18:30"
            times = ", ".join(f"{start:%H:%M}" for start, _, _ in sessions)
            return f"{date_from:%d.%m.%Y} {times}"
        return f"{date_from:%d.%m.%Y %H:%M}–{date_to:%H:%M}"

    def _place_name(self, event_data):
        default = event_data["site"].get("default_place", "")
        venue = self._clean_venue(event_data["venue"].get("seatroot_ru"))
        if venue and venue.lower() != default.lower():
            return f"{default}, {venue}" if default else venue
        return default

    def _adress(self, event_data):
        return (event_data["venue"].get("address_ru") or "").strip() \
            or event_data["site"].get("default_address", "")

    def _category(self, event_data):
        # Box office section first ("ЛЕКЦИИ", "ДЕТЯМ") — it is curated, while
        # keywords in titles misfire ("Арт-занятие на выставке" → выставки)
        title = self._clean_text(event_data["action"].get("event_ru"))
        return (detect_category(event_data.get("kind_name", ""))
                or detect_category(title, self._full_text(event_data)))

    def _poster_imag(self, event_data):
        url = event_data["action"].get("image_url_ru") or ""
        # Some instances only embed base64 images; image_url_* then is a stub
        if url.startswith("http") and "plug" not in url:
            return url
        return None

    def _price(self, event_data):
        prices = event_data.get("prices")
        if not prices:
            return "на сайте"
        if prices == [0]:
            return "бесплатно"
        if len(prices) == 1:
            return f"{prices[0]}₽"
        return f"{prices[0]} - {prices[-1]}₽"

    def _source(self, event_data):
        return self.source

    def _is_registration_open(self, event_data):
        return any(tickets > 0 for _, _, tickets in event_data["sessions"])
