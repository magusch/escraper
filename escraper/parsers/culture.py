from datetime import datetime, timedelta

import json, re

from .base import BaseParser, ALL_EVENT_TAGS
from ..emoji import add_emoji


class Culture(BaseParser):
    name = "culture"
    BASE_URL = "https://www.culture.ru/afisha"
    EVENT_URL = "https://www.culture.ru/events"

    parser_prefix = "CLTR-"
    DATETIME_STRF = "%Y-%m-%dT%H:%M:%S.%fZ"

    def __init__(self):
        self.url = self.BASE_URL
        self.timedelta_hours = self.timedelta_with_gmt0()

    def get_event(self, event_url=None, tags=None):
        if event_url is None:
             raise ValueError("'event_url' required.")
        body = self._request_get(event_url).text

        json_body_min = body.split('<script type="application/ld+json">')[-1].split('</script>')[0]

        self._poster_imag_ = None
        self._poster_imag(json.loads(json_body_min))

        json_body = body.split('<script id="__NEXT_DATA__" type="application/json">')[-1].split('</script>')[0]

        event_json = json.loads(json_body)["props"]["pageProps"]["event"]
        self.event_url = event_url
        event = self.parse(event_json, tags=tags or ALL_EVENT_TAGS)
        return event

    def get_events(self, request_params={}, tags=None, existed_event_ids=[]):
        """
        Parameters:
        -----------
        request_params : dict
            Parameters for culture.ru events

            city : str, default None (sankt-peterburg if None)
                String of city from url to scrape it:
                    sankt-peterburg, kazan(respublika-tatarstan-kazan), ekaterinburg, moscow

            categories : list, default None (all categories)
                All available event catefories:
                    spektakli, kontserti, vstrechi,
                    prazdniki, vistavki, tags-kultura-onlain

            date_from, date_to : str, default None (tomorrow + 5 days)
                Events date range

            days : str, default None (5)
                range beetween date_from and date_to

        tags : list of tags, default all available event tags
            Event tags (title, id, url etc.,
            see all tags in 'escraper.ALL_EVENT_TAGS')

        existed_event_ids : list of eventId that we need to skip
            CLTR-18634405, CLTR-18633215, etc

        Examples:
        ----------
        >>> cltr = Culture()
        >>> request_params = {
            "date_from": "2024-05-01",
            "date_to":   "2024-05-05",
            "city":      "sankt-peterburg"
        }
        >>> cltr.get_events(request_params=request_params)  # doctest: +SKIP
        """

        if "city" in request_params:
            url = self.url + '/' + request_params['city']
        else:
            url = self.url + '/' + "sankt-peterburg"

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
            categories = ['spektakli', 'kontserti', 'vstrechi', 'prazdniki', 'vistavki', 'tags-kultura-onlain']

        events = list()

        for category in categories:
            category_url = url + '/' + category
            scrape_date = date_from
            while scrape_date <= date_to:
                scrape_url = category_url + f"/seanceStartDate-{scrape_date.date()}/seanceEndDate-{scrape_date.date()}"
                response = self._request_get(scrape_url)
                json_body = response.text.split('<script id="__NEXT_DATA__" type="application/json">')[-1].split('</script>')[0]
                event_list_json = json.loads(json_body)["props"]["pageProps"]["events"]["items"]
                for event_json in event_list_json:
                    event_url = self.EVENT_URL + f"/{event_json['_id']}/{event_json['name']}"
                    if event_json['_id'] in existed_event_ids: continue
                    events.append(self.get_event(event_url=event_url, tags=tags))
                    existed_event_ids.append(event_json['_id'])
                scrape_date += timedelta(days=1)

        return events

    def _adress(self, event_json):
        if 'address' in event_json["places"][0] and event_json["places"][0]['address'] is not None:
            full_address = event_json["places"][0]["address"].strip()
            # full_address = full_address.replace("г. Санкт-Петербург, ", "").replace("г Санкт-Петербург, ", "").replace("Санкт-Петербург, ", "")
            # full_address = full_address.replace("Респ. Татарстан, ", "").replace("г. Казань, ", "")
            full_address = ', '.join(re.split('(^г. )|( г. )', full_address)[-1].split(', ')[1:])
        else:
            full_address = ''

        return full_address

    def _category(self, event_json):
        return '' #event_json["organizations"][0]["eipskSourceJson"]["category"]["name"]

    def _date_from(self, event_json):
        today = datetime.today()
        date_from, date_to = None, None
        for date in event_json['seances']:
            if date_from is None:
                if datetime.strptime(date['startDate'], self.DATETIME_STRF) > today:
                    date_from = datetime.strptime(date['startDate'], self.DATETIME_STRF)
                    date_to = datetime.strptime(date['endDate'], self.DATETIME_STRF)
            else:
                if datetime.strptime(date['endDate'], self.DATETIME_STRF)-date_from < timedelta(days=7):
                    date_to = datetime.strptime(date['endDate'], self.DATETIME_STRF)
                else:
                    break
        self._date_from_ = date_from.astimezone(self.TIMEZONE)
        self._date_to_ = date_to.astimezone(self.TIMEZONE)
        return self._date_from_

    def _date_to(self, event_json):
        if self._date_to_ is None:
            self._date_from(event_json)
        return self._date_to_

    def _date_from_to(self, event_json):
        return f"{self._date_from_.date()} – {self._date_to_.date()}"

    def _id(self, event_json):
        return self.parser_prefix + str(event_json["_id"])

    def _place_name(self, event_json):
        if event_json["places"][0]['title']:
            return event_json["places"][0]['title'].strip()
        else:
            return ''

    def _full_text(self, event_json) -> str:
        post_text_html = event_json["text"]
        if post_text_html:
            post_text = self.remove_html_tags(post_text_html.replace("[HTML]", "").replace("[/HTML]", "").replace("<p>", " \n")).strip()
        else:
            post_text = ''
        return post_text

    def _post_text(self, event_json):
        return self.prepare_post_text(self._full_text(event_json))

    def _poster_imag(self, event_json):
        if self._poster_imag_ is None:
            if 'url' not in event_json["image"]:
                self._poster_imag_ = ''
            else:
                self._poster_imag_ = event_json["image"]["url"]
        return self._poster_imag_

    def _price(self, event_json):
        if event_json["priceMin"] is not None:
            return 'от ' + str(event_json["priceMin"]) + '₽'
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
            return event_json["saleLink"]

    def _is_registration_open(self, event_json):
        return event_json["status"] == 'published'
