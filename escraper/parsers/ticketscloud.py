import logging
import re, json, os

from datetime import datetime, timedelta

import pytz
from bs4 import BeautifulSoup

from .base import BaseParser, ALL_EVENT_TAGS
from ..emoji import add_emoji

logger = logging.getLogger(__name__)

ORG_IDS = (
    '5dce558174fd6b0bcaa66524', '5e3d551b44d20ecf697408e4', '5e3bec5fea9c82d6958f8551'
)


def extract_tc_event(event_soup):
    """Return the inline `tc_event = {...};` JSON of a TC event page, or None."""
    for script_tag in event_soup.find_all('script'):
        if not script_tag.contents: continue
        text = script_tag.contents[0]
        if re.match('tc_event', text):
            new_text = '='.join(text.strip().split('=')[1:])[:-1]
            return json.loads(new_text)
    return None


class Ticketscloud(BaseParser):
    name = "Ticketscloud"
    BASE_URL = "https://ticketscloud.org/"

    DATETIME_STRF = "%Y%m%dT%H%M%SZ"
    source = "TC"
    TIMEZONE = pytz.timezone("Europe/Moscow")

    def __init__(self, use_proxy=True):
        super().__init__(use_proxy=use_proxy)
        self.url = self.BASE_URL
        self.TC_TOKEN = os.getenv('TC_TOKEN')
        self.TC_VIBE_REF = os.getenv('TC_VIBE_REF')

    def get_event(self, event_url=None, tags=None):
        if event_url is None:
            raise ValueError("'event_id' or 'event_url' required.")
        self.url = event_url

        event_soup = BeautifulSoup(
            self._request_get(event_url).text, "lxml"
        )

        tags = tags or ALL_EVENT_TAGS

        tc_event = extract_tc_event(event_soup)
        if tc_event is not None:
            self.tc_event = tc_event
        event = self.parse(event_soup, tags=tags)

        return event

    def get_events(self, request_params=None, tags=None, existed_event_ids=None):
        """
        Parameters:
        -----------
        request_params : dict, default None
            org_ids : list
                list of all organization for scraping
            city : str, default 'Санкт-Петербург'
                city to filter events
            days : int, default 10
                max days ahead to include events

        tags : list of tags, default all available event tags
            Event tags (title, id, url etc.,
            see all tags in 'escraper.ALL_EVENT_TAGS')

        Examples:
        ----------
        >>> tcloud = Ticketscloud()
        >>> params = {"org_ids": ['5dce558174fd6b0bcaa66524', '5e3d551b44d20ecf697408e4']}
        >>> tcloud.get_events(request_params=params)  # doctest: +SKIP
        """
        request_params = request_params or {}
        existed_event_ids = list(existed_event_ids) if existed_event_ids else []

        org_ids = request_params.get("org_ids", ORG_IDS)
        days = int(request_params.get("days", 10))
        self.city = request_params.get("city", "Санкт-Петербург")

        for org_id in org_ids:
            url = f"https://{org_id}.ticketscloud.org"
            response = self._request_get(url)

            if response:
                soup = BeautifulSoup(response.text, 'lxml')
                all_events = soup.find('div', class_='u-flex u-flex--wrap')
                if all_events is not None:
                    list_event_from_soup = all_events.find_all('div', class_='ticketscloud-event-item col-md-4')
                else:
                    list_event_from_soup = list()
            else:
                list_event_from_soup = list()
            for event_card in list_event_from_soup:

                self.url = url + event_card.find('a').get('href')

                event_id = self._id_from_url(self.url)
                if event_id in existed_event_ids:
                    continue

                #datetime_str = event_card.find(class_='ticketscloud-event-item__time').text.replace(',', '').strip()
                event_datetime_str = event_card.find(class_='ticketscloud-event-item__time')['datetime']
                event_datetime = datetime.strptime(event_datetime_str, "%Y-%m-%d %H:%M:%S%z")

                city = event_card.find('span', class_=None).text.strip()
                # Filter: keep only events in the requested city (if provided)
                if (self.city and city.lower() != str(self.city).strip().lower()) or \
                        event_datetime > datetime.now().astimezone(self.TIMEZONE) + timedelta(days=days):
                    continue

                event = self.get_event(event_url=self.url)
                existed_event_ids.append(event_id)
                yield event

    def _adress(self, event_soup):
        if not 'address' in self.tc_event['venue']: return
        full_address = self.tc_event['venue']['address']
        if "онлайн" in full_address.lower():
            address = "Онлайн"
        else:
            target_city = str(getattr(self, 'city', '') or '').strip()
            if target_city and full_address.find(f", {target_city}") != -1:
                end_idx = full_address.find(f", {target_city}")
                address = full_address[:end_idx]

            elif target_city and full_address.find(f"{target_city}, ") != -1:
                address = full_address.replace(f"{target_city}, ", "")
            else:
                address = full_address

        return address

    def _category(self, event_soup):
        category = None
        if 'tags' in self.tc_event:
            category = self.tc_event['tags'][0]
        return category

    def _date_from(self, event_soup):
        try:
            return datetime.strptime(self.tc_event['lifetime'].split('\n')[1].strip().split('DATE-TIME:')[-1], self.DATETIME_STRF).astimezone(self.TIMEZONE)
        except ValueError as e:
            logger.warning("TC: failed to parse date_from for event %s: %s", self.tc_event.get('id'), e)
            current_year = datetime.now().year
            return datetime(current_year, 12, 31).astimezone(self.TIMEZONE)

    def _date_to(self, event_soup):
        try:
            return datetime.strptime(self.tc_event['lifetime'].split('\n')[2].strip().split('DATE-TIME:')[-1], self.DATETIME_STRF).astimezone(self.TIMEZONE)
        except ValueError as e:
            logger.warning("TC: failed to parse date_to for event %s: %s", self.tc_event.get('id'), e)
            current_year = datetime.now().year
            return datetime(current_year, 12, 31).astimezone(self.TIMEZONE)

    def _date_from_to(self, event_soup):
        """
        Parse date from and to as string from event page.
        """
        return re.sub(r'\s+', ' ', event_soup.find('div', class_='event-info-se__address-part').find('time').text.strip())

    def _id(self, event_soup):
        return f"{self.source}-{self.tc_event['id']}"

    def _id_from_url(self, event_url):
        event_site_id = event_url.split('?')[0].split('/')[-1]
        return f"{self.source}-{event_site_id}"

    def _place_name(self, event_soup):
        address_name = re.sub(r'\s+', ' ',
                              event_soup.find('div', class_='event-info-se__address-part').find('address').text.strip())
        target_city = str(getattr(self, 'city', '') or '').strip()
        if target_city:
            return re.sub(f'{re.escape(target_city)}, ', '', address_name)
        return address_name

    def _full_text(self, event_soup) -> str:
        if event_soup.find('article',
                     class_='col-md-9 col-sm-12 showroom-event-slide__content showroom-event-slide__content_desc'):
            post_text = re.sub(r'\.(\w)', r'. \1', event_soup.find('article', class_='col-md-9 col-sm-12 showroom-event-slide__content showroom-event-slide__content_desc').find('p').text)
        else:
            post_text = ''
        return post_text

    def _post_text(self, event_soup):
        post_text = self._full_text(event_soup)
        return self.prepare_post_text(post_text)

    def _poster_imag(self, event_soup):
        if 'cover_original' in self.tc_event['media']:
            return self.tc_event['media']['cover_original']['url']
        else:
            return

    def _price(self, event_soup):
        return re.sub(r'\s+', ' ', event_soup.find('div', class_='buy-button-se__button').text.strip())

    def _title(self, event_soup):
        return add_emoji(
            event_soup.find('div', class_='event-info-se__title').text.strip()
        )

    def _url(self, event_soup):
        return self.url

    def _ticket_url(self, event_soup) -> str:
        if self.TC_TOKEN is None:
            return self._url(event_soup)
        return f"https://ticketscloud.com/v1/widgets/common?token={self.TC_TOKEN}&event={self.tc_event['id']}&org={self._org_id(event_soup)}&vibe_ref={self.TC_VIBE_REF}"

    def _source(self, event_soup) -> str:
        return self.source

    def _org_id(self, event_soup):
        return self.tc_event['org']['id']

    def _is_registration_open(self, event_soup):
        return self.tc_event['tickets_amount_vacant']>0