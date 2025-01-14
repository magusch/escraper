import re
import requests
import warnings
from datetime import datetime, timedelta

import pytz
from bs4 import BeautifulSoup

from .base import BaseParser, ALL_EVENT_TAGS
from ..emoji import add_emoji


monthes = {
    "января": "01",
    "февраля": "02",
    "марта": "03",
    "апреля": "04",
    "мая": "05",
    "июня": "06",
    "июля": "07",
    "августа": "08",
    "сентября": "09",
    "октября": "10",
    "ноября": "11",
    "декабря": "12",
}
STRPTIME = "%d %m %H:%M"




class QTickets(BaseParser):
    name = "qtickets"
    BASE_URL = "https://spb.qtickets.events"
    DATETIME_STRF = "%Y-%m-%d"
    parser_prefix = "QT-"

    def __init__(self):
        self.url = self.BASE_URL
        self.timedelta_hours = self.timedelta_with_gmt0()

    def get_event(self, event_url=None, tags=None):
        if event_url is None:
            raise ValueError("'event_id' or 'event_url' required.")

        event_soup = BeautifulSoup(
            self._request_get(event_url).text, "lxml"
        )
        event = self.parse(event_soup, tags=tags or ALL_EVENT_TAGS)

        return event

    def get_events(self, request_params={}, tags=None):
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
        >>> qt = QTickets()
        >>> request_params = {
            "date_to": "2020-01-02",
        }
        >>> qt.get_events(request_params=request_params)  # doctest: +SKIP
        """

        if "city" in request_params:
            self.url = self.url.replace('spb', request_params['city'])

        if "date_to" in request_params:
            date_to = request_params["date_to"]
            if re.match(r"\d{1,2}-\d{1,2}-\d{1,2}", date_to):
                maximum_date = datetime.fromisoformat(date_to)
            else:
                maximum_date = datetime.today() + timedelta(days=10)
        elif "days" in request_params:
            days = int(request_params["days"])
            maximum_date = datetime.today() + timedelta(days=days)
        else:
            maximum_date = datetime.today() + timedelta(days=10)
        maximum_date = maximum_date.astimezone(self.TIMEZONE)

        events = list()
        page = 1
        while True:
            url = f"{self.url}/?page={str(page)}"
            response = self._request_get(url)

            dates = list()
            if response:
                soup = BeautifulSoup(response.text, "lxml")
                list_event_from_soup = soup.find_all("li", {"class": "item"})
            else:
                list_event_from_soup = list()

            for event_card in list_event_from_soup:
                event_url = event_card.find("a")["href"]

                date = datetime.fromisoformat(
                    event_card.find("time", {"class":"place"})['datetime']
                ).astimezone(self.TIMEZONE)
                dates.append(date)
                event_soup = BeautifulSoup(self._request_get(event_url).text, "lxml")
                if date >= maximum_date and len(dates) > 9:
                    continue
                events.append(self.parse(event_soup, tags=tags or ALL_EVENT_TAGS))
            page += 1

            if dates and max(dates) >= maximum_date:
                break

        return events

    def _adress(self, event_soup):
        full_address = event_soup.find(
            "div", {"class": "address"}
        ).text.strip()

        full_address = full_address.replace("Санкт-Петербург, ", "")
        full_address = full_address.replace("Россия", "")

        return full_address

    def _category(self, event_soup):
        return None

    def _date_from(self, event_soup):
        date_string = self._date_from_to(event_soup)
        year_now = datetime.now().year

        day_to = None

        if re.match(r"\w* \d+ \w+", date_string):
            time_split = date_string.split(',')
            hour_from, min_from = time_split[-1].strip().split(':')

            _, day_from, month_name_from = time_split[0].split(' ')
            month_from = int(monthes[month_name_from.strip()])

        else:
            dates = date_string.split('–')

            date_from = dates[0].strip().split(' ')
            month_from = int(monthes[date_from[1].strip()])
            day_from = date_from[0].strip()
            hour_from, min_from = 17, 0

            date_to = dates[1].strip().split(' ')
            month_to = int(monthes[date_to[1].strip()])
            day_to = date_to[0].strip()
            hour_to, min_to = 19, 0

            if month_from < datetime.now().month:
                year_now = year_now - 1

        hour_from = int(hour_from)
        if hour_from > self.timedelta_hours:
            hour_from = hour_from - self.timedelta_hours

        self._date_from_ = datetime(year_now, month_from, int(day_from), hour_from, int(min_from)).astimezone(self.TIMEZONE)

        if not day_to:
            self._date_to_ = self._date_from_ + timedelta(hours=2)
        else:
            if month_to < month_from: year_now = year_now + 1 #add logic for date_from in previous year
            hour_to = int(hour_to)
            if hour_to > self.timedelta_hours:
                hour_to = hour_to - self.timedelta_hours
            self._date_to_ = datetime(year_now, month_to, int(day_to), hour_to, int(min_to)).astimezone(self.TIMEZONE)

        return self._date_from_

    def _date_to(self, event_soup):
        return self._date_to_

    def _date_from_to(self, event_soup):
        """
        Parse date from and to as string from event page.
        """
        return event_soup.find("div", {"class": "event-info"}).find("time").text.strip()


    def _id(self, event_soup):
        event_url = self._url(event_soup)
        if event_url:
            event_id = event_url.split('/')[-1].split('-')[0]
        else:
            event_id = str(datetime.today()).replace(' ','_')
        return self.parser_prefix + event_id

    def _place_name(self, event_soup):
        return event_soup.find("a", {"class": "place"}).text.strip()

    def _full_text(self, event_soup) -> str:
        post_text_soup = event_soup.find("div", {"class": "text"})
        if post_text_soup:
            post_text = self.remove_html_tags(
                event_soup.find("div", {"class": "text"}).text
            ).strip()
        else:
            post_text = ''
        return post_text

    def _post_text(self, event_soup):
        return self.prepare_post_text(self._full_text(event_soup))

    def _poster_imag(self, event_soup):
        event_card_image = event_soup.find("div", {"class": "center_area"}).find("img")
        if event_card_image is not None:
            return event_card_image["src"]

    def _price(self, event_soup):
        return event_soup.find("a", {"id": "buy_btn"}).text.split('Купить от')[-1].strip()

    def _title(self, event_soup):
        return add_emoji(
            event_soup.find("section", {"id": "modal_content"}).find("h1").text.strip()
        )

    def _url(self, event_soup):
        return event_soup.find("link", {"rel": "canonical"})['href']

    def _is_registration_open(self, event_soup):
        return re.match(r"\d+", self._price(event_soup)) is not None
