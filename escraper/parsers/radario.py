import re
import warnings
from datetime import datetime, timedelta

from .base import BaseParser, ALL_EVENT_TAGS
from ..emoji import add_emoji


class Radario(BaseParser):
    name = "radario"
    BASE_URL = "https://radario.ru/events/"
    BASE_EVENTS_API = "https://radario.ru/web-api/affiche/events"
    DATETIME_STRF = "%Y-%m-%dT%H:%M:%S.%f%z"
    parser_prefix = "RADARIO-"

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

    def __init__(self):
        self.url = self.BASE_URL
        self.events_api = self.BASE_EVENTS_API
        self.timedelta_hours = self.timedelta_with_gmt0()

    def get_event(self, event_id=None, event_url=None, tags=None):
        if event_id is None and event_url is not None:
            event_id = event_url.split('/')[-1]
        elif event_url is None and event_id is None :
            raise ValueError("'event_id' or 'event_url' required.")

        event_api_url = f"{self.BASE_EVENTS_API}/{event_id}"
        response = self._request_get(event_api_url)

        if response.status_code != 200:
            raise ValueError(f"Failed to fetch events. HTTP {response.status_code}: {response.text}")

        event_json_data = response.json()
        event = self.parse(event_json_data, tags=tags or ALL_EVENT_TAGS)

        return event

    def get_events(self, request_params=None, tags=None, existed_event_ids=[]):
        """
        Parameters:
        -----------
        request_params : dict
            Parameters for radario events

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

        if "city" in request_params:
            city_id = self.cities_to_id(request_params["city"])
        else:
            city_id = 1


        if request_params.pop("online", False):
            is_online = True
        else:
            is_online = False

        events = list()

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

                        new_event = self.get_event(event_id=event_json['id'], tags=tags or ALL_EVENT_TAGS)

                        events.append(new_event)
                        existed_event_ids.append(new_event.id)
                    if len(list_event_from_json) < limit: break
                    offset += (limit-1)

            else:
                warnings.warn(f"Category {cat!r} is not exist", UserWarning)

        return events

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
            city_name = event_json_data["cityName"]
            if city_name is None: city_name = 'Санкт-Петербург'
            if full_address.find(f", {city_name}") != -1:
                end_idx = full_address.find(f", {city_name}")
                address = full_address[:end_idx]

            elif full_address.find(f"{city_name}, ") != -1:
                address = full_address.replace(f"{city_name}, ", "")
            else:
                address = full_address

        return address

    def _category(self, event_json_data):
        return event_json_data['superTagName'].strip()

    def _date_from(self, event_json_data):
        self._date_from_ = datetime.strptime(event_json_data['beginDate'], self.DATETIME_STRF).astimezone(self.TIMEZONE)
        return self._date_from_

    def _date_to(self, event_json_data):
        self._date_to_ = datetime.strptime(event_json_data['endDate'], self.DATETIME_STRF).astimezone(self.TIMEZONE)
        return self._date_to_

    def _date_from_to(self, event_json_data):
        """
        Parse date from and to as string from event page.
        """
        return f"{self._date_from_}-#{self._date_to_}"

    def _id(self, event_json_data):
        return self.parser_prefix + str(event_json_data["id"])

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
        return self.BASE_URL + self._id(event_json_data).replace(self.parser_prefix, "")

    def _is_registration_open(self, event_json_data):
        return event_json_data["ticketCount"] != 0

    def categories_to_id(self, category):
        categories_to_id = {
            "concert": 1, "theatre": 2,"museum": 3, "education": 4, "sport": 5,
            "entertainment": 6, "kids": 380, "show": 1598, "Active": 1669,
        }
        return categories_to_id[category]

    def cities_to_id(self, city):
        cities_to_id = {
            "spb": 1, "kzn": 85, "msk": 2,
        }
        return cities_to_id[city.lower()]
