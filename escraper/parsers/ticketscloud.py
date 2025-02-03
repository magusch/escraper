import re, json

import warnings
from datetime import datetime, timedelta

import pytz
from bs4 import BeautifulSoup

from .base import BaseParser, ALL_EVENT_TAGS
from ..emoji import add_emoji

ORG_IDS = (
    '5dce558174fd6b0bcaa66524', '5e3d551b44d20ecf697408e4', '5e3bec5fea9c82d6958f8551'
)

class Ticketscloud(BaseParser):
    name = "Ticketscloud"
    BASE_URL = "https://ticketscloud.org/"

    DATETIME_STRF = "%Y%m%dT%H%M%SZ"
    parser_prefix = "TC-"
    TIMEZONE = pytz.timezone("Europe/Moscow")

    def __init__(self):
        self.url = self.BASE_URL

    def get_event(self, event_url=None, tags=None):
        if event_url is None:
            raise ValueError("'event_id' or 'event_url' required.")
        self.url = event_url

        event_soup = BeautifulSoup(
            self._request_get(event_url).text, "lxml"
        )

        tags = tags or ALL_EVENT_TAGS

        script_tags = event_soup.find_all('script')
        for script_tag in script_tags:
            if not script_tag.contents: continue
            text = script_tag.contents[0]
            if re.match('tc_event', text):
                new_text = '='.join(text.strip().split('=')[1:])[:-1]
                self.tc_event = json.loads(new_text)
                break
        event = self.parse(event_soup, tags=tags)

        return event

    def get_events(self, org_ids=None, tags=None, city='spb'):
        """
        Parameters:
        -----------
        org_ids : list
            list of all organization for scraping

        tags : list of tags, default all available event tags
            Event tags (title, id, url etc.,
            see all tags in 'escraper.ALL_EVENT_TAGS')

        Examples:
        ----------
        >>> tcloud = Ticketscloud()
        >>> org_ids = ['5dce558174fd6b0bcaa66524', '5e3d551b44d20ecf697408e4', '5e3bec5fea9c82d6958f8551']
        >>> tags = ("adress",
            "date_from","date_to","place_name",
            "post_text","price",
            "title",
            "url", "org_id", "poster_imag")
        >>> tcloud.get_events(org_ids=org_ids, tags=tags)  # doctest: +SKIP
        """
        if org_ids is None: org_ids = ORG_IDS

        self.city = city
        events = list()

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
                time = datetime.strptime(
                    event_card.find(class_='ticketscloud-event-item__time').text.replace(',', ''), "%d.%m.%Y %H:%M")

                city = event_card.find('span', class_=None).text
                if (city != 'Санкт-Петербург' and self.city == 'spb') or time>datetime.now()+timedelta(days=10):
                    continue

                events.append(self.get_event(event_url=self.url))

        return events

    def _adress(self, event_soup):
        if not 'address' in self.tc_event['venue']: return
        full_address = self.tc_event['venue']['address']
        if "онлайн" in full_address.lower():
            address = "Онлайн"
        else:
            if full_address.find(", Санкт-Петербург") != -1:
                end_idx = full_address.find(", Санкт-Петербург")
                address = full_address[:end_idx]

            elif full_address.find("Санкт-Петербург, ") != -1:
                address = full_address.replace("Санкт-Петербург, ", "")
            else:
                address = full_address

        return address

    def _category(self, event_soup):
        category = None
        if 'tags' in self.tc_event:
            category = self.tc_event['tags'][0]
        return category

    def _date_from(self, event_soup):
        return datetime.strptime(self.tc_event['lifetime'].split('\n')[1].strip().split('DATE-TIME:')[-1], self.DATETIME_STRF).astimezone(self.TIMEZONE)

    def _date_to(self, event_soup):
        return datetime.strptime(self.tc_event['lifetime'].split('\n')[2].strip().split('DATE-TIME:')[-1], self.DATETIME_STRF).astimezone(self.TIMEZONE)

    def _date_from_to(self, event_soup):
        """
        Parse date from and to as string from event page.
        """
        return re.sub('\s+', ' ', event_soup.find('div', class_='event-info-se__address-part').find('time').text.strip())

    def _id(self, event_soup):
        return self.parser_prefix + self.tc_event['id']

    def _place_name(self, event_soup):
        address_name = re.sub('\s+', ' ',
                              event_soup.find('div', class_='event-info-se__address-part').find('address').text.strip())
        return re.sub('Санкт-Петербург, ', '', address_name)

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
        return re.sub('\s+', ' ', event_soup.find('div', class_='buy-button-se__button').text.strip())

    def _title(self, event_soup):
        return add_emoji(
            event_soup.find('div', class_='event-info-se__title').text.strip()
        )

    def _url(self, event_soup):
        return self.url

    def _org_id(self, event_soup):
        return self.tc_event['org']['id']


    def _is_registration_open(self, event_soup):
        return self.tc_event['tickets_amount_vacant']>0