from datetime import datetime
import os
import itertools
import re
from pathlib import Path

import pytz

from .base import BaseParser, ALL_EVENT_TAGS
from .utils import STRPTIME
from ..emoji import add_emoji


class Timepad(BaseParser):
    """
    Parse ivents from www.timepad.ru by API:
    http://dev.timepad.ru/api/what-api-can/

    Methods:
    --------

    get_events(event_id=None, event_url=None)
        Getting event parameters from timepad. Requieres one argument
        from following:

        event_id : int or string, default None
            event id on timepad (...timepad.ru/event/{event_id})

        event_url : str, default None
            url to event on timepad.ru
    """

    name = "timepad"
    url = "www.timepad.ru"
    events_api = "https://api.timepad.ru/v1/events"
    parser_prefix = "TIMEPAD-"
    TIMEZONE = pytz.timezone("Europe/Moscow")
    FIELDS = (  # event fields in timepad request parameters
        "name",
        "starts_at",
        "organization",
        "description_short",
        "description_html",
        "ends_at",
        "location",
        "poster_image",
        "url",
        "registration_data",
        "ticket_types",
        "id",
        "categories",
    )

    def __init__(self, token=None):
        if token is None:
            if "TIMEPAD_TOKEN" in os.environ:
                token = os.environ.get("TIMEPAD_TOKEN")

            else:
                raise ValueError("Timepad token was not found.")

        self._token = token
        self.headers = dict(Authorization=f"Bearer {self._token}")

    def get_event(self, event_id=None, event_url=None, tags=None):
        if event_url is not None:
            event_id = re.findall(r"(?<=event/)\d*(?=/)", event_url)[0]

        if event_id is None:
            raise ValueError("'event_id' or 'event_url' required.")

        url = self.events_api + f"/{event_id}"
        response_json = self._request_get(url, headers=self.headers).json()

        if not is_moderated(response_json):
            print("Event is not moderated")
            event = None

        else:
            tags = tags or ALL_EVENT_TAGS
            event = self.parse(response_json, tags=tags)

        return event

    def get_events(self, request_params=None, tags=None):
        """
        Parameters:
        -----------
        request_params : dict, default None
            Parameters for timepad events
            (for more details see. http://dev.timepad.ru/api/get-v1-events/)

            limit : int, default 10
                1 <= limit <= 100
                events count

            sort : str
                sorting field (id, or starts_at, etc.)

            category_ids : str like "id1, id2, id3, ..."
                see Timepad().event_categories

            category_ids_exclude : str like "id1, id2, id3, ..."
                see Timepad().event_categories
                event categories that exclude

            cities : str like "city1, city2, city3, ..."
                event city

            keywords : str like "key1, key2, key3, ..."
                event name keywords

            keywords_exclude : str like "key1, key2, key3, ..."
                excluded event name keywords

            access_statuses : str like "status1, status2, ..."
                available statuses:
                private, draft, link_only, public

            price_min, price_max : int
                min and max ticket price:
                for price_min - at least one ticket, that have greater price
                for price_max - at least one ticket, that have lower price

            starts_at_min, starts_at_max : datetime string format %Y-%m-%dT%H:%M:%S%z
                event starts dates

            created_at_min, created_at_max : datetime string format %Y-%m-%dT%H:%M:%S%z
                event created dates

        tags : list of tags, default all available event tags
            Event tags (title, id, url etc.,
            see all tags in 'escraper.ALL_EVENT_TAGS')

        Examples:
        ---------
        >>> tp = Timepad()

        Select by city:
        >>> params = dict(cities="Санкт-Петербург")
        >>> tp.get_events(request_params=params)
        <list of 10 events from Санкт-Петербург>

        Select by category_ids:
        >>> tp.event_categories
        [
            {'id': '217', 'name': 'Бизнес', 'tag': 'business'},
            {'id': '374', 'name': 'Кино', 'tag': 'cinema'},
            {'id': '376', 'name': 'Спорт', 'tag': 'sport'},
            ...
        ]
        >>> params = dict(category_ids="217, 374"])
        >>> tp.get_events(request_params=params)
        <list of 10 events by business or/and cinema>

        Select by starts_at_min:
        >>> params = dict(starts_at_min="2020-08-11T00:00:00")
        <10 events after that starts after "2020-08-11T00:00:00">
        """
        request_params = request_params or {}
        if "fields" not in request_params:
            request_params["fields"] = ", ".join(self.FIELDS)

        tags = tags or ALL_EVENT_TAGS

        url = self.events_api + ".json"
        res = self._request_get(url, params=request_params, headers=self.headers)

        events_data = list()
        if res:
            for response_json in res.json()["values"]:
                if is_moderated(response_json):
                    events_data.append(self.parse(response_json, tags=tags))
                else:
                    events_data.append(None)

        return events_data

    def _adress(self, event):
        if "city" not in event["location"]:
            address = "Онлайн"

        else:
            if "address" not in event["location"]:
                if event["location"]["city"] == "Без города":
                    address = "Онлайн"

                elif event["location"]["city"]:
                    address = event["location"]["city"]

                elif "coordinates" in event["location"]:
                    address = ", ".join(
                        map(str, event["location"]["coordinates"])
                    )  # coordinates, realy?

                else:
                    raise TypeError(
                        "Unknown address type: {}".format(event["location"])
                    )

            else:
                address = event["location"]["address"].strip()


        return self.remove_html_tags(address)

    def _category(self, event):
        """
        TODO create more flexible detection categories
        """
        return event["categories"][0]["name"]

    def _date_from(self, event):
        dt = datetime.strptime(event["starts_at"], STRPTIME).astimezone(self.TIMEZONE)

        return dt

    def _date_to(self, event):
        if "ends_at" in event:
            dt = datetime.strptime(event["ends_at"], STRPTIME).astimezone(self.TIMEZONE)
            return dt
        return None

    def _date_from_to(self, event):
        """
        Timepad return date_from and date_to instead.
        """
        return None

    def _id(self, event):
        return self.parser_prefix + str(event["id"])

    def _place_name(self, event):
        return self.remove_html_tags(event["organization"]["name"]).strip()

    def _full_text(self, event):
        if event.get("description_html"):
            full_text = self.remove_html_tags(event["description_html"])
        elif event.get("description_short"):
            full_text = self.remove_html_tags(event["description_short"])
        else:
            full_text = ""

        return full_text

    def _post_text(self, event):
        post_text = ""

        if event.get("description_short"):
            post_text = self.remove_html_tags(event["description_short"])

        elif event.get("description_html"):
            post_text = self.remove_html_tags(event["description_html"])

        else:
            post_text = ""

        return self.prepare_post_text(post_text)

    def _poster_imag(self, event):
        if "poster_image" not in event:
            return None

        return event["poster_image"]["uploadcare_url"][2:]

    def _price(self, event):
        if event["registration_data"]["is_registration_open"]:
            price_min_in_answer = event["registration_data"]["price_min"]
            price_min = event["registration_data"]["price_max"]

            for ticket in event["ticket_types"]:
                if ticket["price"] == price_min_in_answer and ticket["status"] == "ok":
                    price_min = price_min_in_answer
                    break
                elif ticket["price"] < price_min and ticket["status"] == "ok":
                    price_min = ticket["price"]

            if price_min == 0:
                price_text = "Бесплатно"
            elif price_min > 0:
                price_text = f"{price_min}₽"

        else:
            price_text = "Билетов нет"

        return price_text

    def _title(self, event):
        return add_emoji(self.remove_html_tags(event["name"]))

    def _url(self, event):
        return event["url"]

    def _is_registration_open(self, event):
        return int(event["registration_data"]["is_registration_open"])

    @property
    def event_categories(self):
        """
        Getting list of events categories.

        Return:
        -------
        [dict(id=str, name=str, tag=str), ...]

        Example:
        --------
        [
            {'id': '217', 'name': 'Бизнес', 'tag': 'business'},
            {'id': '374', 'name': 'Кино', 'tag': 'cinema'},
            {'id': '376', 'name': 'Спорт', 'tag': 'sport'},
            ...
        ]
        """
        url = "https://api.timepad.ru/v1/dictionary/event_categories"
        return self._request_get(url, headers=self.headers).json()["values"]

    @property
    def event_statuses(self):
        """
        Getting list of events statuses.

        Return:
        -------
        [dict(id=str, name=str), ...]

        Example:
        --------
        [
            {'id': 'ok', 'name': 'Ok'},
            {'id': 'deleted', 'name': 'Удалена'},
            {'id': 'inactive', 'name': 'Неактивна'}
        ]
        """
        url = "https://api.timepad.ru/v1/dictionary/event_statuses"
        return self._request_get(url, headers=self.headers).json()["values"]

    @property
    def tickets_statuses(self):
        """
        Getting list of tickets statuses.

        Return:
        -------
        [dict(id=str, name=str), ...]

        Example:
        --------
        [
            {'id': 'notpaid', 'name': 'просрочено'},
            {'id': 'ok', 'name': 'бесплатно'},
            {'id': 'paid', 'name': 'оплачено'},
            ...
        ]
        """
        url = "https://api.timepad.ru/v1/dictionary/tickets_statuses"
        return self._request_get(url, headers=self.headers).json()["values"]


def is_moderated(response_json):
    return response_json["moderation_status"] != "not_moderated"
