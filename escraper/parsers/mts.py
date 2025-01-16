from datetime import datetime, timedelta

import json

from .base import BaseParser, ALL_EVENT_TAGS
from ..emoji import add_emoji


class MTS(BaseParser):
    name = "mts"
    BASE_URL = "https://live.mts.ru"
    parser_prefix = "MTS-"
    DATETIME_STRF = "%Y-%m-%dT%H:%M:%S%z"

    def __init__(self):
        self.url = self.BASE_URL
        self.timedelta_hours = self.timedelta_with_gmt0()

    def get_event(self, event_url=None, tags=None):
        if event_url is None:
             raise ValueError("'event_url' required.")
        body = self._request_get(event_url).text
        json_body = body.split('<script id="__NEXT_DATA__" type="application/json">')[-1].split('</script>')[0]

        event_json = json.loads(json_body)["props"]["pageProps"]["initialState"]["Announcements"]["announcementDetails"]
        self.event_url = event_url
        event = self.parse(event_json, tags=tags or ALL_EVENT_TAGS)
        return event

    def get_events(self, request_params={}, tags=None, existed_event_ids=[]):
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
        >>> mts.get_events(request_params=request_params)  # doctest: +SKIP
        """

        if "city" in request_params:
            url = self.url + '/' + request_params['city']
        else:
            url = self.url + '/'  + "sankt-peterburg"

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

        events = list()

        for category in categories:

            category_url = url + '/collections/' + category
            scrape_date = date_from
            while scrape_date <= date_to:
                scrape_url = category_url + f"?date={scrape_date.date()}"
                response = self._request_get(scrape_url)
                json_body = response.text.split('<script id="__NEXT_DATA__" type="application/json">')[-1].split('</script>')[0]
                event_list_json = json.loads(json_body)["props"]["pageProps"]["initialState"]["Announcements"]["announcementPreviewCollection"]["items"]

                for event_json in event_list_json:
                    event_url = self.url + event_json['url']
                    event_id = self._id_from_url(event_url)
                    if event_id in existed_event_ids: continue
                    events.append(self.get_event(event_url=event_url, tags=tags))
                    existed_event_ids.append(event_id)

                scrape_date += timedelta(days=1)

        return events


    def _adress(self, event_json):
        if 'address' in event_json["venue"] and event_json["venue"]['address'] is not None:
            full_address = event_json["venue"]["address"].strip()
            full_address = full_address.replace("г. Санкт-Петербург, ", "").replace("г Санкт-Петербург, ", "").replace("Санкт-Петербург, ", "")
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

    def _id_from_url(self, event_url):
        event_id = event_url.split('eventId=')[-1].split('&')[0].split('#')[0]
        return self.parser_prefix + event_id

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

    def _is_registration_open(self, event_json):
        return event_json["status"] == 'TicketsOnSale'
