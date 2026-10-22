import json, os
import logging
import re
import time
from datetime import datetime, timedelta

from .base import BaseParser, ALL_EVENT_TAGS
from .utils import require_city_name, strip_city
from ..emoji import add_emoji

logger = logging.getLogger(__name__)


class MTS(BaseParser):
    name = "mts"
    BASE_URL = "https://live.mts.ru"
    source = "MTS"
    DATETIME_STRF = "%Y-%m-%dT%H:%M:%S%z"
    REQUEST_DELAY = 0.5
    DEFAULT_REQUEST_TIMEOUT = 40

    def __init__(self, use_proxy=True):
        super().__init__(use_proxy=use_proxy)
        self.url = self.BASE_URL
        self.timedelta_hours = self.timedelta_with_gmt0()
        self.ticket_url_template = os.getenv("MTS_TICKET_URL_TEMPLATE", "")

    def get_event(self, event_url=None, tags=None):
        if event_url is None:
             raise ValueError("'event_url' required.")
        body = self._request_get(event_url).text
        json_body = body.split('<script id="__NEXT_DATA__" type="application/json">')[-1].split('</script>')[0]

        try:
            event_json = json.loads(json_body)
        except json.JSONDecodeError:
            raise ValueError("Can't parse event json from page")

        event_json = event_json["props"]["pageProps"]["initialState"]["Announcements"]["announcementDetails"]
        self.event_url = event_url
        event = self.parse(event_json, tags=tags or ALL_EVENT_TAGS)
        return event

    def get_events(self, request_params=None, tags=None, existed_event_ids=None):
        """
        Parameters:
        -----------
        request_params : dict
            Parameters for mts live events

            city : str, default None (sankt-peterburg if None)
                String of city from url to scrape it:
                    sankt-peterburg, kazan, ekaterinburg, moscow

            categories : list, default None (all categories except children and excursions )
                All available event catefories:
                    ribbon, concerts, theater, musicals,
                    children, show, festivals, exhibitions,
                    excursions, sport

            date_from, date_to : str, default None (tomorrow + 5 days)
                Events date range

            days : str, default None (5)
                range beetween date_from and date_to

        tags : list of tags, default all available event tags
            Event tags (title, id, url etc.,
            see all tags in 'escraper.ALL_EVENT_TAGS')

        existed_event_ids : list of eventId that we need to skip
            MTS-18634405, MTS-18633215, etc

        Examples:
        ----------
        >>> mts = MTS()
        >>> request_params = {
            "date_from": "2024-05-01",
            "date_to":   "2024-05-05",
            "city":      "sankt-peterburg"
        }
        >>> list(mts.get_events(request_params=request_params))  # doctest: +SKIP

        Yields parsed events one at a time as they are scraped (generator).
        """
        request_params = request_params or {}
        existed_event_ids = list(existed_event_ids) if existed_event_ids else []

        city = str(request_params.get("city") or "sankt-peterburg").strip().lower()
        require_city_name(city, self.source)
        url = self.url + '/' + city
        city_checked = False

        if "date_from" in request_params:
            date_from = datetime.strptime(request_params["date_from"], '%Y-%m-%d')
        else:
            date_from = datetime.today() + timedelta(days=2)

        if "date_to" in request_params:
            date_to = datetime.strptime(request_params["date_to"], '%Y-%m-%d')
        elif "days" in request_params:
            date_to = date_from + timedelta(days=int(request_params['days']))
        else:
            date_to = date_from + timedelta(days=5)

        if "categories" in request_params:
            categories = request_params["categories"]
        else:
            categories = ["ribbon", "concerts", "theater", "musicals", "show", "festivals", "exhibitions", "sport"]

        for category in categories:

            category_url = url + '/collections/' + category
            scrape_date = date_from
            while scrape_date <= date_to:
                scrape_url = category_url + f"?date={scrape_date.date()}"
                response = self._request_get(scrape_url, return_on_status=(404,))
                if not city_checked and response is not None and response.status_code == 404:
                    raise ValueError(f"{self.source}: unknown city {city!r} ({scrape_url} is 404)")
                if not response:
                    break
                city_checked = True

                json_body = self._extract_announcement_collection(response.text)
                if json_body is None:
                    logger.warning("MTS: announcementCollection not found on %s", scrape_url)
                    scrape_date += timedelta(days=1)
                    continue

                event_list_json = json_body.get("items") or []

                for event_json in event_list_json:
                    event_city = self._city_from_url(event_json['url'])
                    if event_city and event_city != city:
                        logger.warning("MTS: skipping %s — listed for %s, requested %s",
                                       event_json['url'], event_city, city)
                        continue
                    event_url = self.url + event_json['url']
                    event_id = self._id_from_url(event_url)
                    if event_id in existed_event_ids: continue
                    try:
                        event = self.get_event(event_url=event_url, tags=tags)
                    except (ValueError, KeyError, json.JSONDecodeError) as e:
                        logger.warning("MTS: skipping event %s: %s", event_url, e)
                        time.sleep(2)
                        continue
                    existed_event_ids.append(event_id)
                    yield event

                scrape_date += timedelta(days=1)

    def _extract_announcement_collection(self, page_text):
        """Locate and decode the announcementCollection JSON from MTS Next.js RSC payload.

        MTS embeds the page data inside multiple <script>self.__next_f.push([N,"..."])</script>
        blocks. The content of each push is a JS-string-encoded chunk of the RSC stream; a
        single logical JSON object (such as announcementCollection) is frequently split across
        several chunks. We concatenate all push payloads, decode their JS-string escapes, then
        brace-balance the first announcementCollection object that contains an ``items`` field.
        """
        push_re = re.compile(r'self\.__next_f\.push\(\[\s*\d+\s*,\s*"((?:\\.|[^"\\])*)"\s*\]\)', re.DOTALL)
        chunks = []
        for m in push_re.finditer(page_text):
            try:
                chunks.append(json.loads('"' + m.group(1) + '"'))
            except json.JSONDecodeError:
                continue

        if chunks:
            combined = ''.join(chunks)
        else:
            # Fallback: treat the page itself as a single already-decoded stream.
            # This keeps the parser working for simpler/inline fixtures or future formats.
            combined = page_text.replace('\\"', '"')

        marker = '"announcementCollection":'
        pos = 0
        while True:
            idx = combined.find(marker, pos)
            if idx == -1:
                return None
            start = combined.find('{', idx + len(marker))
            if start == -1:
                return None

            block = self._balanced_json_object(combined, start)
            pos = idx + len(marker)
            if block is None:
                continue
            try:
                obj = json.loads(block)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict) and 'items' in obj:
                return obj

    @staticmethod
    def _balanced_json_object(text, start):
        """Return text[start:end+1] where text[start] == '{' and braces are balanced.

        Tracks JSON string state so braces inside strings don't affect depth. Returns
        None if no balanced object is found before the end of ``text``.
        """
        depth = 0
        in_string = False
        i = start
        n = len(text)
        while i < n:
            c = text[i]
            if in_string:
                if c == '\\' and i + 1 < n:
                    i += 2
                    continue
                if c == '"':
                    in_string = False
            else:
                if c == '"':
                    in_string = True
                elif c == '{':
                    depth += 1
                elif c == '}':
                    depth -= 1
                    if depth == 0:
                        return text[start:i + 1]
            i += 1
        return None


    def _adress(self, event_json):
        if 'address' in event_json["venue"] and event_json["venue"]['address'] is not None:
            full_address = strip_city(event_json["venue"]["address"], self._city_from_url(self.event_url))
        else:
            full_address = ''

        return full_address

    def _category(self, event_json):
        return event_json["category"]["title"]

    def _date_from(self, event_json):
        self._date_from_ = datetime.strptime(event_json["eventClosestDateTime"]+'Z', self.DATETIME_STRF).astimezone(self.TIMEZONE)
        return self._date_from_

    def _date_to(self, event_json):
        date_to = datetime.strptime(event_json["lastEventDateTime"]+'Z', self.DATETIME_STRF).astimezone(self.TIMEZONE)
        if (date_to < self._date_from_ + timedelta(days=7)) and (date_to != self._date_from_):
            self._date_to_ = date_to
        elif self._date_from_:
            self._date_to_ = self._date_from_ + timedelta(hours=3)
        else:
            self._date_to_ = None

        return self._date_to_

    def _date_from_to(self, event_json):
        return f"{self._date_from_} – {self._date_to_}"

    def _id(self, event_json):
        return self._id_from_url(self.event_url)

    @staticmethod
    def _city_from_url(event_url):
        """City slug of an announcement URL: .../kazan/announcements/... → "kazan"."""
        match = re.search(r"(?:^|live\.mts\.ru)/([^/?#]+)/announcements/", event_url or "")
        return match.group(1) if match else None

    def _id_from_url(self, event_url):
        event_id = event_url.split('eventId=')[-1].split('&')[0].split('#')[0]
        return f"{self.source}-{event_id}"

    def _place_name(self, event_json):
        return event_json["venue"]["title"].strip()

    def _full_text(self, event_json) -> str:
        post_text_html = event_json["description"]
        if post_text_html:
            post_text = self.remove_html_tags(post_text_html.replace("<p>", " \n")).strip()
        else:
            post_text = ''
        return post_text

    def _post_text(self, event_json):
        return self.prepare_post_text(self._full_text(event_json))

    def _poster_imag(self, event_json):
        if 'media' not in event_json or len(event_json['media'])==0:
            return None
        return event_json['media'][0]["url"]

    def _price(self, event_json):
        if event_json["eventMinPrice"] is not None:
            return str(event_json["eventMinPrice"]) + '₽'
        else:
            return 'на сайте'

    def _title(self, event_json):
        return add_emoji(
            event_json["title"].strip()
        )

    def _url(self, event_json):
        if self.event_url is not None:
            return self.event_url
        else:
            return 'https://live.mts.ru' + event_json["url"]

    def _ticket_url(self, event_json) -> str:
        return self.ticket_url_template + self._url(event_json)

    def _source(self, event_json) -> str:
        return self.source

    def _is_registration_open(self, event_json):
        return event_json["status"] == 'TicketsOnSale'
