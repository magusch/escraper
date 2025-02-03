import warnings
from abc import ABC, abstractmethod
from datetime import datetime
from collections import namedtuple

from json.decoder import JSONDecodeError

import requests
import pytz
from bs4 import BeautifulSoup

ALL_EVENT_TAGS = (
    "adress",
    "category",
    "date_from",
    "date_to",
    "date_from_to",
    "id",
    "place_name",
    "post_text",
    "full_text",
    "poster_imag",
    "price",
    "title",
    "url",
    "is_registration_open",
)


class BaseParser(ABC):
    MAX_NUMBER_CONNECTION_ATTEMPTS = 3
    TIMEZONE = pytz.timezone("Europe/Moscow")
    TIMEZONE_zero = pytz.timezone("Europe/London")

    @abstractmethod
    def get_event(self):
        """Get one event by url / event_id"""

    @abstractmethod
    def get_events(self) -> list:
        """Get events by request parameters (date from-to, keywords etc.)"""

    @abstractmethod
    def _adress(self) -> str:
        """Event adress"""

    @abstractmethod
    def _category(self) -> str:
        """Event category"""

    @abstractmethod
    def _date_from(self) -> datetime:
        """Event date from"""

    @abstractmethod
    def _date_to(self) -> datetime:
        """Event date to (may be None)"""

    @abstractmethod
    def _date_from_to(self) -> str:
        """Event date from-to in readable string format (may be None)"""

    @abstractmethod
    def _id(self) -> str:
        """PARSER_PREFIX-ID"""

    @abstractmethod
    def _place_name(self) -> str:
        """Event place name"""

    @abstractmethod
    def _post_text(self) -> str:
        """Event post text"""

    @abstractmethod
    def _full_text(self) -> str:
        """Event post text"""

    @abstractmethod
    def _poster_imag(self) -> str:
        """Event poster image (may be None)"""

    @abstractmethod
    def _price(self) -> str:
        """Event ticket price"""

    @abstractmethod
    def _title(self) -> str:
        """Event title"""

    @abstractmethod
    def _is_registration_open(self) -> bool:
        """Event registration status"""

    def parse(self, event_data, tags=None):
        if tags is None:
            raise ValueError("'tags' for event required (see escraper.ALL_EVENT_TAGS).")

        data = dict()
        for tag in tags:
            try:
                data[tag] = getattr(self, "_" + tag)(event_data)
            except AttributeError:
                raise TypeError(
                    f"Unsupported event tag found: {tag}.\n"
                    f"All available event tags: {ALL_EVENT_TAGS}."
                )

        DataStorage = namedtuple("event", tags)

        return DataStorage(**data)

    def remove_html_tags(self, data):
        return BeautifulSoup(data, "lxml").text

    def _request_get(self, *args, **kwargs):
        """
        Send get request with specific arguments.

        To avoid internet connection issues,
        will catch ConnectionError and retry.
        """
        attempts_count = 0

        while True:
            try:
                response = requests.get(*args, **kwargs)

                if not response.ok:
                    if response.content:
                        try:
                            response_status = response.json()["response_status"]
                        except JSONDecodeError:
                            response_status = {"error_code": response.status_code, "message": "Invalid JSON response"}
                        except Exception as e:
                            response_status = {"error_code": response.status_code, "message": str(e)}
                    else:
                        response_status = dict(
                            error_code=response.status_code,
                            message="response content is empty",
                        )

                    warning_msg = "Bad response: {status_code}: {message}.".format(
                        status_code=response_status["error_code"],
                        message=response_status["message"],
                    )

                    if attempts_count == self.MAX_NUMBER_CONNECTION_ATTEMPTS:
                        response = None
                        warnings.warn(warning_msg + "\nBreak (event counts 0)", UserWarning)
                        break

                    warnings.warn(warning_msg + "\nRetry", UserWarning)
                    attempts_count += 1

                else:
                    break

            except requests.ConnectionError as e:
                if attempts_count == self.MAX_NUMBER_CONNECTION_ATTEMPTS:
                    raise e
                attempts_count += 1
                print("Retry connection")

        return response

    def prepare_post_text(self, post_text):
        if len(post_text) > 550:
            sentences = post_text.split(".")
            post = ""
            for s in sentences:
                if len(post) < 365:
                    post = post + s + "."
                else:
                    post_text = post
                    break
        return post_text

    def timedelta_with_gmt0(self):
        now = datetime.today()

        return now.astimezone(self.TIMEZONE).hour - now.astimezone(self.TIMEZONE_zero).hour
