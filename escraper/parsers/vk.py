import os, time
from datetime import datetime, timedelta

import requests

from .base import BaseParser, ALL_EVENT_TAGS
from .utils import DEFAULT_CITY_NAME, require_city_name

from ..emoji import add_emoji

divide_list = lambda lst, sz: [lst[i:i+sz] for i in range(0, len(lst), sz)]

class VK(BaseParser):
    name = "VK"
    BASE_URL = 'https://vk.com/'
    BASE_URL_API = "https://api.vk.com/method/"

    source = "VK"
    quantity = 1000
    count_query = 100

    def __init__(self, token=None, use_proxy=True):
        super().__init__(use_proxy=use_proxy)
        if token is None:
            if "VK_TOKEN" in os.environ:
                token = os.environ['VK_TOKEN']
            else:
                raise ValueError("VK token was not found.")
        if "VK_ID" in os.environ:
            user_id = os.environ['VK_ID']
        else:
            raise ValueError("VK_ID was not found.")
        self.get_end_str = f'&access_token={token}&expires_in=86400&user_id={user_id}&v=5.103'

    def get_token(self, client_id ):
        url = f"https://oauth.vk.com/authorize?client_id={client_id}&display=page&redirect_uri=http://vk.com/&scope=groups,wall&response_type=token&v=5.131&state=123456"

    def get_event(self, event_id=None, event_url=None, city=None):
        """Get one event by url / event_id"""
        if event_url:
            event_id = event_url.split('/')[-1].split('?')[0]
        event_in_list = self.get_full_event(event_id)
        if event_in_list:
            event = event_in_list[0]
            event['_city'] = city or DEFAULT_CITY_NAME
            return self.parse(event, tags=ALL_EVENT_TAGS)

    def get_events(self, request_params=None, existed_event_ids=None):
        """
                Parameters:
                -----------
                request_params : dict, default None
                    Parameters for timepad events
                    (for more details see. http://dev.timepad.ru/api/get-v1-events/)

                    days : int, default 15
                        how many days from today to search for events

                    city_id : int, default 2
                        event city (2=>St.Petersburg)

                    city : str, default 'Санкт-Петербург'
                        city name or slug, used as address / place name for
                        events without an address. Required with a city_id
                        other than 2, and vice versa.
                Examples:
                ---------
                >>> vk = VK()

                Select by city:
                >>> params = dict(days=15)
                >>> list(vk.get_events(request_params=params))
                <list of events from Санкт-Петербург>

                Yields parsed events one at a time per id-chunk (generator).
            """

        request_params = request_params or {}
        existed_event_ids = list(existed_event_ids) if existed_event_ids else []
        if 'days' in request_params:
            days = request_params['days']
        else:
            days = 15

        city_id = int(request_params.get('city_id', 2))
        city = require_city_name(request_params.get('city'), self.source)
        # city_id drives the search, city only labels events: they must agree.
        if (city_id == 2) != (city == DEFAULT_CITY_NAME):
            raise ValueError(
                f"{self.source}: set both 'city_id' and 'city' for a city other than "
                f"{DEFAULT_CITY_NAME} (got city_id={city_id}, city={city!r})"
            )

        event_data_general = []
        offset_count_query = 0
        while self.quantity > offset_count_query:
            res = self.request_events(count=self.count_query, offset=offset_count_query, city_id=city_id)
            if 'items' not in res: assert f"Error: {res}"
            event_data_general += res['items']
            offset_count_query += self.count_query
            if res['count'] < self.quantity: self.quantity = res['count']
            time.sleep(0.5)

        event_ids = self.get_ids(event_data_general, existed_event_ids)
        for event_ids_divided in divide_list(event_ids, 200):
            chunk = self.get_full_event(event_ids_divided)
            for event in self.check_events(chunk, days):
                event['_city'] = city
                yield self.parse(event, tags=ALL_EVENT_TAGS)
            time.sleep(0.5)

    def request_events(self, q='%20', city_id=2, count=250, offset=0):
        site = f'{self.BASE_URL_API}/groups.search?q={q}&type=event&future=1&city_id={city_id}&count={count}&offset={offset}{self.get_end_str}'
        req = self._request_get(site)
        if not req:
            return {}
        events = req.json()
        if 'response' not in events:
            return {}
        return events['response']

    def get_ids(self, events, existed_event_ids=[]):
        return [event['id'] for event in events if f"{self.source}-{event['id']}" not in existed_event_ids]

    def get_full_event(self, ids):
        if len(ids) < 500:
            site = f"{self.BASE_URL_API}/groups.getById?group_ids={ids}&fields=addresses,site,description,status,cover,place,start_date,finish_date{self.get_end_str}"
            req = self._request_get(site)
            if not req:
                return []
            response = req.json()
            if 'response' in response:
                return response['response']
            return []

    def check_events(self, events, days=31):
        bad_events_index = list()
        for i, event in enumerate(events):
            from_date = datetime.fromtimestamp(int(event['start_date']))
            if datetime.today() > from_date or from_date > datetime.today()+timedelta(days=days):
                bad_events_index.append(i)
            elif 'finish_date' in event:
                if datetime.fromtimestamp(int(event['finish_date'])) > from_date + timedelta(days=days):
                    bad_events_index.append(i)
        bad_events_index.reverse()
        for i in bad_events_index: events.pop(i)
        return events

    def add_address(self, event):
        site = f"{self.BASE_URL_API}/groups.getAddresses?group_id={event['id']}&address_ids={event['addresses']['main_address_id']}&fields=title,address{self.get_end_str}"
        req = self._request_get(site)
        if req:
            addresses = req.json()
            if addresses['response']['count'] > 0:
                event['addresses']['address'] = addresses['response']['items'][0]['address']
                event['addresses']['place_name'] = addresses['response']['items'][0]['title']
        if "address" not in event.get('addresses'):
            event['addresses']['address'] = ''
            event['addresses']['place_name'] = ''
        time.sleep(0.25)
        return event

    def _adress(self, event):
        if "main_address_id" in event['addresses']:
            if "address" not in event['addresses']:
                event = self.add_address(event)
            address_id = event['addresses']['address']
            return address_id
        return event.get('_city', DEFAULT_CITY_NAME)

    def _category(self, event):
        return 'vk'

    def _date_from(self, event):
        return datetime.fromtimestamp(int(event['start_date'])).astimezone(self.TIMEZONE)

    def _date_to(self, event):
        if "finish_date" in event:
            return datetime.fromtimestamp(int(event['finish_date'])).astimezone(self.TIMEZONE)
        return None

    def _date_from_to(self, event):
        """Event date from-to in readable string format (may be None)"""
        return None

    def _id(self, event):
        return f"{self.source}-{event['id']}"

    def _place_name(self, event):
        if "main_address_id" in event['addresses']:
            if "address" not in event['addresses']:
                event = self.add_address(event)
            return event['addresses']['place_name']
        return event.get('_city', DEFAULT_CITY_NAME)

    def _full_text(self, event) -> str:
        post_text = event['description']
        return post_text

    def _post_text(self, event):
        return self.prepare_post_text(self._full_text(event))

    def _poster_imag(self, event):
        if event['cover']['enabled']!=0:
            cover_url = event['cover']['images'][-1]['url']
            return cover_url
        else:
            return None

    def _url(self, event):
        if 'screen_name' in event:
            return f"{self.BASE_URL}{event['screen_name']}"

        return self._ticket_url(event)

    def _ticket_url(self, event):
        if event['site'] != '':
            if event['site'].startswith('http'):
                return event['site']
            else:
                return 'http://' + event['site']
        else:
            return None


    def _price(self, event):
        return "во встрече"

    def _title(self, event):
        return add_emoji(event["name"])

    def _source(self, event) -> str:
        return self.source

    def _is_registration_open(self, event):
        return self._date_from(event) > datetime.today().astimezone(self.TIMEZONE)

