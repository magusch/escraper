import json
import re
from datetime import datetime, timedelta

import pytz

from .base import BaseParser, ALL_EVENT_TAGS
from .utils import require_city_name, strip_city
from ..emoji import add_emoji


def _deref_nuxt(data, idx, depth=0):
    """Resolve a packed Nuxt __NUXT_DATA__ array reference to its Python value."""
    if idx is None or depth > 10 or idx < 0 or idx >= len(data):
        return None
    v = data[idx]
    if isinstance(v, list) and len(v) == 2 and v[0] in ('Ref', 'Reactive', 'ShallowReactive', 'EmptyRef'):
        if v[0] == 'EmptyRef':
            return None
        return _deref_nuxt(data, v[1], depth + 1)
    if isinstance(v, dict):
        return {k: _deref_nuxt(data, vi, depth + 1) if isinstance(vi, int) and vi >= 0 else vi
                for k, vi in v.items()}
    if isinstance(v, list):
        return [_deref_nuxt(data, vi, depth + 1) if isinstance(vi, int) and vi >= 0 else vi
                for vi in v]
    return v


def _parse_kassir_dt(date_str):
    """Parse a kassir.ru datetime string to a Moscow-aware datetime.

    kassir.ru stores Moscow local time but with a misleading '+00:00' offset.
    The value should be interpreted as Moscow local time, not UTC.
    """
    dt = datetime.strptime(date_str[:19], "%Y-%m-%dT%H:%M:%S")
    return pytz.timezone("Europe/Moscow").localize(dt)


class Kassir(BaseParser):
    """Parser for spb.kassir.ru and other kassir.ru city domains.

    Uses the kassir.ru search API for get_events() and parses
    __NUXT_DATA__ from activity pages for get_event().
    """

    name = "kassir"
    BASE_URL = "https://spb.kassir.ru"
    API_BASE = "https://api.kassir.ru/api"
    source = "KASSIR"
    REQUEST_DELAY = 1.0

    DEFAULT_CATEGORIES = [
        "koncert", "teatr", "shou", "festivali", "sport", "detyam",
    ]

    def __init__(self, use_proxy=True):
        super().__init__(use_proxy=use_proxy)
        self.event_url = None

    def get_event(self, event_url=None, tags=None):
        """Fetch and parse a single kassir.ru activity page.

        Parameters
        ----------
        event_url : str
            Full URL of the activity page, e.g.
            https://spb.kassir.ru/koncert/irina-ponarovskaya-5d667a6d7597b
        tags : list, optional
            Event tags to return. Defaults to ALL_EVENT_TAGS.
        """
        if event_url is None:
            raise ValueError("'event_url' required.")

        body = self._request_get(event_url).text

        nuxt_match = re.search(r'id="__NUXT_DATA__">(.*?)</script>', body, re.DOTALL)
        if not nuxt_match:
            raise ValueError("Can't find __NUXT_DATA__ on page")

        nuxt_data = json.loads(nuxt_match.group(1))

        pinia = None
        for item in nuxt_data:
            if isinstance(item, dict) and 'activity.store' in item:
                pinia = item
                break

        if pinia is None:
            raise ValueError("Can't find pinia stores in page data")

        activity_store = _deref_nuxt(nuxt_data, pinia['activity.store'])
        venue_store = _deref_nuxt(nuxt_data, pinia.get('venue.store', -1))

        event_data = {
            'activity': (activity_store or {}).get('activityState', {}),
            'venue': (venue_store or {}).get('venueState', {}),
            'city': event_url.split('//')[-1].split('/')[0],
        }

        self.event_url = event_url
        return self.parse(event_data, tags=tags or ALL_EVENT_TAGS)

    def get_events(self, request_params=None, tags=None, existed_event_ids=None):
        """Fetch events from the kassir.ru search API.

        Parameters
        ----------
        request_params : dict
            city_domain : str, default "spb.kassir.ru"
                Domain of the city site to scrape.
                Examples: spb.kassir.ru, msk.kassir.ru

            categories : list of str
                Category slugs to fetch. Defaults to DEFAULT_CATEGORIES:
                    koncert, teatr, shou, festivali, sport, detyam

            date_from, date_to : str 'YYYY-MM-DD'
                Date range for events. Defaults to tomorrow + 5 days.

            days : int
                Number of days from date_from. Used when date_to is absent.

        tags : list, optional
            Event tags to return. Defaults to ALL_EVENT_TAGS.

        existed_event_ids : list
            Activity IDs to skip, e.g. ["KASSIR-21295", "KASSIR-272231"].

        Examples
        --------
        >>> kassir = Kassir()
        >>> kassir.get_events(request_params={
        ...     "date_from": "2026-03-14",
        ...     "date_to": "2026-03-20",
        ...     "categories": ["koncert"],
        ... })  # doctest: +SKIP

        Yields parsed events one at a time as search pages are fetched (generator).
        """
        request_params = request_params or {}
        existed_event_ids = list(existed_event_ids) if existed_event_ids else []

        city_domain = request_params.get('city_domain') or 'spb.kassir.ru'
        require_city_name(city_domain, self.source)
        categories = request_params.get('categories', self.DEFAULT_CATEGORIES)

        if 'date_from' in request_params:
            date_from = datetime.strptime(request_params['date_from'], '%Y-%m-%d')
        else:
            date_from = datetime.today() + timedelta(days=2)

        if 'date_to' in request_params:
            date_to = datetime.strptime(request_params['date_to'], '%Y-%m-%d')
        elif 'days' in request_params:
            date_to = date_from + timedelta(days=int(request_params['days']))
        else:
            date_to = date_from + timedelta(days=5)

        date_from_str = date_from.strftime('%Y-%m-%d')
        date_to_str = date_to.strftime('%Y-%m-%d')

        for category_slug in categories:
            skip = 0
            take = 100
            while True:
                url = (
                    f"{self.API_BASE}/search"
                    f"?domain={city_domain}"
                    f"&take={take}&skip={skip}"
                    f"&categorySlug={category_slug}"
                    f"&dateFrom={date_from_str}&dateTo={date_to_str}"
                )
                response = self._request_get(url)
                if not response:
                    break

                result = json.loads(response.text)
                items = result.get('items', [])
                if not items:
                    break

                for item in items:
                    obj = item['object']
                    event_id = f"{self.source}-{obj['id']}"
                    if event_id in existed_event_ids:
                        continue

                    venues = obj.get('venues') or []
                    venue = venues[0] if venues else {}

                    event_data = {
                        'activity': obj,
                        'venue': venue,
                        'city': city_domain,
                    }
                    self.event_url = obj.get('url', '')
                    event = self.parse(event_data, tags=tags or ALL_EVENT_TAGS)
                    existed_event_ids.append(event_id)
                    yield event

                pagination = result.get('pagination', {})
                total = pagination.get('totalCount', 0)
                skip += take
                if skip >= total:
                    break

    def _adress(self, event_data):
        addr = (event_data.get('venue') or {})
        addr = (addr.get('address') or {}).get('addressString', '') or ''
        return strip_city(addr, event_data.get('city'))

    def _category(self, event_data):
        cat = event_data['activity'].get('category') or {}
        parent = cat.get('parent')
        return (parent or cat).get('name', '')

    def _date_from(self, event_data):
        date_str = event_data['activity']['dateRange']['beginsAt']
        self._date_from_ = _parse_kassir_dt(date_str)
        return self._date_from_

    def _date_to(self, event_data):
        date_str = event_data['activity']['dateRange']['endsAt']
        self._date_to_ = _parse_kassir_dt(date_str)
        if self._date_from_:
            if self._date_to_ - self._date_from_ > timedelta(days=3):
                self._date_to_ = self._date_from_ + timedelta(hours=3)

        return self._date_to_

    def _date_from_to(self, event_data):
        return f"{self._date_from_} – {self._date_to_}"

    def _id(self, event_data):
        return f"{self.source}-{event_data['activity']['id']}"

    def _place_name(self, event_data):
        return (event_data.get('venue') or {}).get('name', '')

    def _full_text(self, event_data):
        html = event_data['activity'].get('description') or ''
        if html:
            html = re.sub(r'<p[^>]*>', ' \n', html)
            return self.remove_html_tags(html).strip()
        return ''

    def _post_text(self, event_data):
        return self.prepare_post_text(self._full_text(event_data))

    def _poster_imag(self, event_data):
        return event_data['activity'].get('posterImage')

    def _price(self, event_data):
        price_range = event_data['activity'].get('priceRange') or {}
        min_price = price_range.get('min')
        if min_price is not None:
            return str(int(min_price)) + '₽'
        return 'на сайте'

    def _title(self, event_data):
        return add_emoji(event_data['activity']['title'].strip())

    def _url(self, event_data):
        if self.event_url:
            return self.event_url
        return event_data['activity'].get('url', '')

    def _ticket_url(self, event_data):
        return self._url(event_data)

    def _source(self, event_data):
        return self.source

    def _is_registration_open(self, event_data):
        # Search API provides activeEventsCount; activity page HTML does not.
        active_count = event_data['activity'].get('activeEventsCount')
        if active_count is not None:
            return bool(active_count)
        # Fallback: if a price range exists, assume tickets are on sale.
        price_range = event_data['activity'].get('priceRange') or {}
        return price_range.get('min') is not None
