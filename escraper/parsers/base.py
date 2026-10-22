import logging
import time
from abc import ABC, abstractmethod
from datetime import datetime
from collections import namedtuple
from typing import Iterator
from urllib.parse import urlsplit

from json.decoder import JSONDecodeError

import os

import requests
import pytz
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


def _short_url(url):
    """Strip query string for compact retry logs. Full URL goes only into final error."""
    if not url:
        return url
    parts = urlsplit(str(url))
    if not parts.netloc:
        return url
    return f"{parts.scheme}://{parts.netloc}{parts.path}"

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
    "ticket_url",
    "source",
    "is_registration_open",
)


class BaseParser(ABC):
    MAX_NUMBER_CONNECTION_ATTEMPTS = 3
    DEFAULT_REQUEST_TIMEOUT = 20
    TIMEZONE = pytz.timezone("Europe/Moscow")
    TIMEZONE_zero = pytz.timezone("Europe/London")
    # Minimum seconds between two successful _request_get calls on the same instance.
    # Subclasses can override (raise for fragile sources, set to 0 to disable).
    REQUEST_DELAY = 0.5
    source = 'OTHER'

    def __init__(self, use_proxy=True):
        self.use_proxy = use_proxy
        self._last_request_time = 0.0

    @abstractmethod
    def get_event(self):
        """Get one event by url / event_id"""

    @abstractmethod
    def get_events(self) -> Iterator:
        """Get events by request parameters (date from-to, keywords etc.).

        Implementations are generators: they yield parsed events one at a time
        as they are scraped, so a consumer can process partial results even if
        scraping later fails mid-way. Wrap in ``list(...)`` if you need a list.
        """

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
    def _url(self) -> str:
        """Event URL"""

    @abstractmethod
    def _ticket_url(self) -> str:
        """Event ticket URL (may be None)"""
        return None

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
    def _source(self) -> str:
        """Event source"""
        return self.source

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

        ``return_on_status`` — HTTP statuses (e.g. ``(404,)``) returned to the
        caller at once, without retries. The response is falsy (``not ok``), so
        ``if not response`` checks keep working, but the caller can inspect
        ``status_code`` to tell "not found" apart from a network failure.
        """
        attempts_count = 0
        return_on_status = tuple(kwargs.pop("return_on_status", ()))
        if "timeout" not in kwargs:
            kwargs["timeout"] = self.DEFAULT_REQUEST_TIMEOUT

        if "proxies" not in kwargs and self.use_proxy and "PROXY" in os.environ:
            proxy = os.environ["PROXY"]
            kwargs["proxies"] = {"http": proxy, "https": proxy}

        if "headers" not in kwargs:
            kwargs["headers"] = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
            }

        url = args[0] if args else kwargs.get("url")
        short_url = _short_url(url)
        max_attempts = self.MAX_NUMBER_CONNECTION_ATTEMPTS

        if self.REQUEST_DELAY:
            elapsed = time.monotonic() - self._last_request_time
            wait = self.REQUEST_DELAY - elapsed
            if wait > 0:
                time.sleep(wait)

        while True:
            try:
                response = requests.get(*args, **kwargs)
                self._last_request_time = time.monotonic()

                if not response.ok and response.status_code in return_on_status:
                    break

                if not response.ok:
                    response_content = response.content
                    if response_content:
                        try:
                            response_status = response.json()["response_status"]
                        except JSONDecodeError:
                            response_status = {
                                "error_code": response.status_code,
                                "message": f"Invalid JSON response. Response content: {response_content}",
                            }
                        except Exception as e:
                            response_status = {"error_code": response.status_code, "message": str(e)}
                    else:
                        response_status = dict(
                            error_code=response.status_code,
                            message="response content is empty",
                        )

                    if attempts_count == max_attempts:
                        logger.error(
                            "%s: bad response %s on %s — giving up after %d attempts: %s | full url: %s",
                            self.source, response_status["error_code"], short_url,
                            max_attempts, response_status["message"], url,
                        )
                        response = None
                        break

                    logger.warning(
                        "%s: bad response %s on %s — retry %d/%d: %s",
                        self.source, response_status["error_code"], short_url,
                        attempts_count + 1, max_attempts, response_status["message"],
                    )
                    attempts_count += 1
                    time.sleep(2 ** attempts_count)

                else:
                    break

            except requests.ConnectionError as e:
                if attempts_count >= max_attempts:
                    logger.error(
                        "%s: connection error on %s — giving up after %d attempts: %s | full url: %s",
                        self.source, short_url, max_attempts, e, url,
                    )
                    response = None
                    break
                attempts_count += 1
                time.sleep(2 ** attempts_count)
                logger.warning(
                    "%s: connection error on %s — retry %d/%d: %s",
                    self.source, short_url, attempts_count, max_attempts, e,
                )

            except requests.Timeout as e:
                if attempts_count >= max_attempts:
                    logger.error(
                        "%s: timeout on %s — giving up after %d attempts: %s | full url: %s",
                        self.source, short_url, max_attempts, e, url,
                    )
                    response = None
                    break
                attempts_count += 1
                time.sleep(2 ** attempts_count)
                logger.warning(
                    "%s: timeout on %s — retry %d/%d: %s",
                    self.source, short_url, attempts_count, max_attempts, e,
                )

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
