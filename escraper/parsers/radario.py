import logging
import re
from datetime import datetime, timedelta

from .base import BaseParser, ALL_EVENT_TAGS
from .utils import DEFAULT_CITY_NAME, strip_city
from ..emoji import add_emoji

logger = logging.getLogger(__name__)


class Radario(BaseParser):
    name = "radario"
    BASE_URL = "https://radario.ru/events/"
    BASE_EVENTS_API = "https://radario.ru/web-api/affiche/events"
    CITIES_API = "https://radario.ru/web-api/affiche/cities"
    DATETIME_STRF = "%Y-%m-%dT%H:%M:%S.%f%z"
    source = "RADARIO"

    AVAILABLE_CATEGORIES = [
        "concert",
        "theatre",
        "museum",
        "education",
        "sport",
        "entertainment",
        "kids",
        "show",
    ]

    def __init__(self, use_proxy=True):
        super().__init__(use_proxy=use_proxy)
        self.url = self.BASE_URL
        self.events_api = self.BASE_EVENTS_API
        self.timedelta_hours = self.timedelta_with_gmt0()
        self._cities = None

    def get_event(self, event_id=None, event_url=None, tags=None, city_name=None):
        if event_id is None and event_url is not None:
            event_id = event_url.split('/')[-1]
        elif event_url is None and event_id is None :
            raise ValueError("'event_id' or 'event_url' required.")

        event_api_url = f"{self.BASE_EVENTS_API}/{event_id}"
        response = self._request_get(event_api_url)

        if not response or response.status_code != 200:
            raise ValueError(f"Failed to fetch events. HTTP {response.status_code}: {response.text}")

        event_json_data = response.json()
        if not event_json_data.get("cityName"):
            event_json_data["cityName"] = city_name or DEFAULT_CITY_NAME
        event = self.parse(event_json_data, tags=tags or ALL_EVENT_TAGS)

        return event

    def get_events(self, request_params=None, tags=None, existed_event_ids=None):
        """
        Parameters:
        -----------
        request_params : dict
            Parameters for radario events

            city : str or int, default "spb"
                Radario city alias (spb, msk, kzn, ekb, ...), Russian name
                or numeric cityId — see https://radario.ru/web-api/affiche/cities

            online : bool
                Include online events

            category : list, default None (all categories)
                All available event catefories:
                    concert, theatre, museum, education,
                    sport, entertainment, kids, show

            date_from, date_to : str, default None (now)
                Events date range

        tags : list of tags, default all available event tags
            Event tags (title, id, url etc.,
            see all tags in 'escraper.ALL_EVENT_TAGS')

        Examples:
        ----------
        >>> radario = Radario()
        >>> request_params_general = {
            "online": True,
            "category": ["concert", "education", "theatre"],
            "date_from": "2020-01-01",
            "date_to": "2020-01-02",
        }
        >>> radario.get_events(request_params_general=request_params)  # doctest: +SKIP
        """
        request_params = (request_params or dict())
        existed_event_ids = list(existed_event_ids) if existed_event_ids else []

        city_id, city_name = self.resolve_city(request_params.get("city", "spb"))

        if request_params.pop("online", False):
            is_online = True
        else:
            is_online = False

        limit = 21
        offset = 0

        from_date = datetime.today() + timedelta(days=1)
        if 'days' in request_params.keys():
            to_date = from_date + timedelta(days=int(request_params["days"]))
        else:
            to_date = from_date + timedelta(days=8)

        for cat in request_params.pop("category", [""]):
            if cat in self.AVAILABLE_CATEGORIES + [""]:
                while 100 >= offset:
                    events_request_params = {
                        "from": from_date.strftime("%Y-%m-%dT%H:%M:%S+03:00"),
                        "to": to_date.strftime("%Y-%m-%dT%H:%M:%S+03:00"),
                        "cityId": city_id,
                        "limit": limit,
                        "offset": offset,
                        "online": is_online
                    }

                    if cat != "":
                        events_request_params["superTagId"] = self.categories_to_id(cat)

                    response = self._request_get(self.BASE_EVENTS_API, params=events_request_params)

                    if response:
                        list_event_from_json = response.json()
                    else:
                        list_event_from_json = list()
                    for event_json in list_event_from_json:
                        event_id = self._id(event_json)
                        if event_id in existed_event_ids: continue

                        new_event = self.get_event(event_id=event_json['id'], tags=tags or ALL_EVENT_TAGS,
                                                   city_name=city_name)

                        existed_event_ids.append(new_event.id)
                        yield new_event
                    if len(list_event_from_json) < limit: break
                    offset += (limit-1)

            else:
                logger.warning("RADARIO: category %r does not exist", cat)

    def _adress(self, event_json_data):
        full_address = event_json_data['placeAddress'].strip()

        full_address = full_address.replace(", Центральный район", "")

        # remove zip code
        full_address = re.sub(r" \d+ ", " ", full_address)
        full_address = re.sub(r" \d+, ", " ", full_address)
        full_address = re.sub(r"^\d+, ", "", full_address)

        if "онлайн" in full_address.lower():
            address = "Онлайн"
        else:
            city_name = event_json_data.get("cityName") or DEFAULT_CITY_NAME
            if full_address.find(f", {city_name}") != -1:
                end_idx = full_address.find(f", {city_name}")
                address = full_address[:end_idx]

            else:
                address = strip_city(full_address, city_name)

        return address

    def _category(self, event_json_data):
        return event_json_data['superTagName'].strip()

    def _date_from(self, event_json_data):
        self._date_from_ = datetime.strptime(event_json_data['beginDate'], self.DATETIME_STRF) - timedelta(hours=self.timedelta_hours)
        self._date_from_ = self._date_from_.astimezone(self.TIMEZONE)
        return self._date_from_

    def _date_to(self, event_json_data):
        self._date_to_ = datetime.strptime(event_json_data['endDate'], self.DATETIME_STRF) - timedelta(hours=self.timedelta_hours)
        self._date_to_ = self._date_to_.astimezone(self.TIMEZONE)
        return self._date_to_

    def _date_from_to(self, event_json_data):
        """
        Parse date from and to as string from event page.
        """
        return f"{self._date_from_}-#{self._date_to_}"

    def _id(self, event_json_data):
        return f"{self.source}-{event_json_data['id']}"

    def _place_name(self, event_json_data):
        return event_json_data["placeTitle"].strip()

    def _full_text(self, event_json_data) -> str:
        if event_json_data["description"]:
            return self.remove_html_tags(
                event_json_data["description"].replace(
                    "<br/>", "\n"
                )
            )
        else:
            return ""

    def _post_text(self, event_json_data):
        return self.prepare_post_text(self._full_text(event_json_data))

    def _poster_imag(self, event_json_data):
        event_image = event_json_data["imageUri"]
        if event_image is not None:
            return event_image

    def _price(self, event_json_data):
        return str(event_json_data["minPrice"]).split('.')[0] + event_json_data["currency"].replace('RUB', '₽')

    def _title(self, event_json_data):
        return add_emoji(event_json_data["title"].strip())

    def _url(self, event_json_data):
        return self.BASE_URL + str(event_json_data["id"])

    def _is_registration_open(self, event_json_data):
        return event_json_data["ticketCount"] != 0

    def _ticket_url(self, event_json_data):
        return None

    def _source(self, event_json_data) -> str:
        return self.source

    def categories_to_id(self, category):
        categories_to_id = {
            "concert": 1, "theatre": 2,"museum": 3, "education": 4, "sport": 5,
            "entertainment": 6, "kids": 380, "show": 1598, "Active": 1669,
        }
        return categories_to_id[category]

    def cities_to_id(self, city):
        return self.resolve_city(city)[0]

    BUILTIN_CITIES = [
        {"id": 1, "alias": "spb", "name": "Санкт-Петербург"},
        {"id": 2, "alias": "msk", "name": "Москва"},
        {"id": 85, "alias": "kzn", "name": "Казань"},
    ]

    def resolve_city(self, city):
        """Resolve a city alias / Russian name / cityId to ``(city_id, city_name)``.

        Known cities resolve without a request; others are looked up in
        radario's city directory (fetched once per parser instance).
        Raises ValueError for an unknown city.
        """
        found = self._find_city(self.BUILTIN_CITIES, city)
        if found:
            return found

        if self._cities is None:
            response = self._request_get(self.CITIES_API)
            try:
                self._cities = response.json() if response else []
            except ValueError:
                self._cities = []
            if not self._cities:
                logger.warning("RADARIO: city directory unavailable at %s", self.CITIES_API)

        found = self._find_city(self._cities, city)
        if found:
            return found
        raise ValueError(f"RADARIO: unknown city {city!r}")

    @staticmethod
    def _find_city(cities, city):
        key = str(city).strip().lower()
        for item in cities:
            if not isinstance(item, dict):
                continue
            if key in (str(item.get("id")), str(item.get("alias") or "").lower(),
                       str(item.get("name") or "").lower()):
                return item["id"], item["name"]
        return None
