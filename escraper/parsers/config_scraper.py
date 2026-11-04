import hashlib
import logging
import re
from datetime import datetime, timedelta
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from .base import BaseParser, ALL_EVENT_TAGS
from .configs import SITES
from .utils import detect_category
from ..emoji import add_emoji

logger = logging.getLogger(__name__)


MONTHS_RU = {
    "январ": 1, "янв": 1, "феврал": 2, "фев": 2, "март": 3, "мар": 3,
    "апрел": 4, "апр": 4, "мая": 5, "май": 5, "июн": 6, "июл": 7,
    "август": 8, "авг": 8, "сентябр": 9, "сен": 9, "октябр": 10, "окт": 10,
    "ноябр": 11, "ноя": 11, "декабр": 12, "дек": 12,
}

TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "yo",
    "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "kh", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}




class ConfigScraper(BaseParser):
    name = "config"
    source = "CFG"
    DEFAULT_EVENT_HOUR = 19

    def __init__(self, use_proxy=True):
        super().__init__(use_proxy=use_proxy)
        self._current_event = {}
        self._current_config = {}

    @staticmethod
    def _resolve_config(site):
        """Resolve site config: str → lookup in SITES, dict → use directly."""
        if isinstance(site, dict):
            return site
        if isinstance(site, str) and site in SITES:
            return SITES[site]
        raise ValueError(f"Unknown site: {site!r}. Pass a config dict or a registered site name.")

    @staticmethod
    def _extract_field(soup, selector, attr=None):
        if selector is None:
            return None
        el = soup.select_one(selector)
        if el is None:
            return None
        if attr:
            value = el.get(attr)
        else:
            value = el.get_text(" ", strip=True)
        if value:
            return value.strip()
        return None

    @staticmethod
    def _parse_russian_date(text):
        """Parse Russian date like '1 февраля', '21 ноября 2025'."""
        if not text:
            return None
        text = re.sub(r'\s+', ' ', text.strip())
        for match in re.finditer(r'(?<!\d)(\d{1,2})\s+(\S+)(?:\s+(\d{4}))?', text):
            month_str = match.group(2).lower().rstrip(',')
            month = None
            for prefix, num in MONTHS_RU.items():
                if month_str.startswith(prefix):
                    month = num
                    break
            if month is None:
                continue

            day = int(match.group(1))
            year = int(match.group(3)) if match.group(3) else datetime.now().year
            try:
                return datetime(year, month, day)
            except ValueError:
                return None
        return None

    @staticmethod
    def _parse_russian_date_range(text):
        """Parse Russian date strings with optional time.

        Supports:
          '21 февраля, 19:00'
          'с 1 февраля по 28 февраля'
          '24 декабря – 15 февраля'
          'по 6 марта' / 'до 6 марта'
          '2-7 ноября' (day range within one month)
          '26 октября - 2 ноября' (spaced hyphen)
          '1 февраля'
        Leading labels are skipped: 'Выставка | 8 октября – 12 декабря'.
        """
        if not text:
            return None, None, None

        # Commas are noise: "13 июля , 2026 12:00 , Пн" → "13 июля 2026 12:00 Пн"
        text = re.sub(r'\s+', ' ', text.replace(',', ' ').strip())

        # Extract time like "19:00" anywhere in the string
        time_str = None
        time_match = re.search(r'\d{1,2}:\d{2}', text)
        if time_match:
            time_str = time_match.group(0)
            text = (text[:time_match.start()] + text[time_match.end():]).strip()
            text = re.sub(r'\s+', ' ', text)

        text = re.sub(r'^.*?(?=\b[сС]\s+\d|\b(?:по|до)\s+\d|\d)', '', text, count=1)

        match = re.match(r'(\d{1,2})\s*[-–—]\s*(\d{1,2})\s+(\S+(?:\s+\d{4})?)', text)
        if match:
            d_to = ConfigScraper._parse_russian_date(f"{match.group(2)} {match.group(3)}")
            if d_to:
                d_from = d_to.replace(day=int(match.group(1))) if int(match.group(1)) <= d_to.day else None
                return d_from, d_to, time_str

        # "с X по Y" pattern
        match = re.match(r'[сС]\s+(.+?)\s+(?:по|до)\s+(.+)', text)
        if match:
            d_from = ConfigScraper._parse_russian_date(match.group(1))
            d_to = ConfigScraper._parse_russian_date(match.group(2))
            return d_from, d_to, time_str

        # "X – Y" pattern (dash-separated range)
        parts = re.split(r'\s+-\s+|\s*[–—]\s*', text)
        if len(parts) == 2:
            d_from = ConfigScraper._parse_russian_date(parts[0])
            d_to = ConfigScraper._parse_russian_date(parts[1])
            if d_from or d_to:
                return d_from, d_to, time_str

        # "по Y" / "до Y" only
        match = re.match(r'(?:по|до)\s+(.+)', text)
        if match:
            d_to = ConfigScraper._parse_russian_date(match.group(1))
            return None, d_to, time_str

        # Single date
        d_from = ConfigScraper._parse_russian_date(text)
        return d_from, None, time_str

    @staticmethod
    def _parse_date_range(date_str, date_format="%d.%m.%Y"):
        """Parse date string. Returns (date_from, date_to, time_str).

        Supports strptime format or 'russian' for Russian text dates.
        """
        if not date_str:
            return None, None, None

        if date_format == "russian":
            return ConfigScraper._parse_russian_date_range(date_str)

        # Split by dash variants
        parts = re.split(r'[–—-]', date_str.strip())

        date_from, date_to = None, None
        try:
            date_from = datetime.strptime(parts[0].strip(), date_format)
        except (ValueError, TypeError):
            pass

        if len(parts) > 1:
            try:
                date_to = datetime.strptime(parts[-1].strip(), date_format)
            except (ValueError, TypeError):
                pass

        return date_from, date_to, None

    @staticmethod
    def _transliterate(text):
        """Transliterate Cyrillic text to Latin."""
        result = []
        for ch in text.lower():
            result.append(TRANSLIT.get(ch, ch))
        return "".join(result)

    @staticmethod
    def _slug_from_url(url):
        """Extract clean slug from event URL (no query params, fragments)."""
        parsed = urlparse(url)
        path = parsed.path.rstrip("/").split("/")
        slug = path[-1] if path else ""
        slug = re.sub(r'[^\w-]', '', slug)
        return slug

    @staticmethod
    def _make_short_id(title, max_slug_len=21, salt=""):
        """Generate short ID slug from title: first letters of words + hash.

        Example: 'Дима Устинов. Music for a really long walk' -> 'du-mfarlw-a1b2'
        Fits within max_slug_len (default 21 = 30 - len('CFG-XXXX-')).

        `salt` (e.g. the date string) distinguishes recurring events that
        share a title but happen on different dates.
        """
        hash_source = (title + salt).encode()
        # Remove emoji and punctuation, keep words
        clean = re.sub(r'[^\w\s]', ' ', title)
        words = clean.split()
        if not words:
            return hashlib.md5(hash_source).hexdigest()[:8]

        # First letters of each word, transliterated
        initials = ""
        for w in words:
            letter = ConfigScraper._transliterate(w[0]) if w else ""
            initials += letter

        # Short hash for uniqueness (from full title + salt)
        short_hash = hashlib.md5(hash_source).hexdigest()[:4]

        # Budget: max_slug_len, need '-' + hash (5 chars)
        budget = max_slug_len - len(short_hash) - 1
        if budget < 1:
            return short_hash

        initials = initials[:budget]
        return f"{initials}-{short_hash}"

    def _parse_listing_card(self, card, config):
        """Extract event data from a listing card element."""
        # Get URL: from card href (if <a>) or from nested link
        href = card.get("href", "")
        if not href:
            link_sel = config.get("card_link_selector")
            if link_sel:
                link = card.select_one(link_sel)
                if link:
                    href = link.get("href", "")

        title = self._extract_field(card, config.get("card_title_selector")) or ""
        date_str = self._extract_field(card, config.get("card_date_selector"))
        image = self._extract_field(
            card, config.get("card_image_selector"), config.get("card_image_attr")
        )
        if config.get("card_image_attr") == "style":
            if not config.get("card_image_selector"):
                image = card.get("style")
            match = re.search(r"url\(\s*['\"]?([^'\")]+)", image or "")
            image = match.group(1).strip() if match else None
        # Fallback: try src if data-original is empty
        if not image:
            image = self._extract_field(
                card, config.get("card_image_selector"), "src"
            )
        category = self._extract_field(card, config.get("card_category_selector"))
        description = self._extract_field(card, config.get("card_description_selector"))
        place = self._extract_field(card, config.get("card_place_selector"))
        address = self._extract_field(card, config.get("card_address_selector"))
        price = self._extract_field(card, config.get("card_price_selector"))

        # Build URL — if href exists use it, otherwise generate from listing URL + title slug
        if href:
            full_url = href if href.startswith("http") else urljoin(config["base_url"], href)
        else:
            full_url = config["base_url"] + config.get("listing_url", "/")

        data = {
            "url": full_url,
            "title": title,
            "date_str": date_str,
            "image": image,
        }
        if category:
            data["category"] = category
        if description:
            data["description"] = description
        if place:
            data["place"] = place
        if address:
            data["address"] = address
        if price:
            data["price"] = price
        return data

    def get_event(self, event_url=None, tags=None, site=None, card_data=None):
        if event_url is None:
            raise ValueError("'event_url' required.")
        if site is None:
            raise ValueError("'site' required.")

        config = self._resolve_config(site)
        self._current_config = config

        # Start with card data from listing (if available)
        data = dict(card_data) if card_data else {}
        data.setdefault("url", event_url)

        # Fetch detail page unless skip_detail is set
        if not config.get("skip_detail"):
            response = self._request_get(event_url)
            if response:
                soup = BeautifulSoup(response.text, "lxml")

                if not data.get("title"):
                    title = self._extract_field(soup, "h1")
                    if not title:
                        title = self._extract_field(soup, ".infopage_head_page")
                    data["title"] = title or ""

                desc_selector = config.get("description_selector")
                if config.get("description_all") and desc_selector:
                    # Description split over sibling blocks (<p>…</p><p>…</p>)
                    parts = (el.get_text(" ", strip=True) for el in soup.select(desc_selector))
                    description = "\n".join(p for p in parts if p)
                else:
                    description = self._extract_field(soup, desc_selector)
                if description:
                    data["description"] = self.remove_html_tags(description)
                else:
                    data.setdefault("description", "")

                time_str = self._extract_field(soup, config.get("time_selector"))
                if time_str:
                    data["time"] = time_str.strip()

                if not data.get("place"):
                    place = self._extract_field(soup, config.get("place_selector"))
                    if place:
                        data["place"] = place

                if not data.get("date_str"):
                    data["date_str"] = self._extract_field(soup, ".date")

                price = self._extract_field(soup, config.get("price_selector"))
                if price:
                    data["price"] = price

                if not data.get("image"):
                    for sel in [".col-sm-8 img[src*='/upload/']", "img[src*='/upload/']"]:
                        img = soup.select_one(sel)
                        if img:
                            data["image"] = img.get("src")
                            break

        data.setdefault("title", "")
        data.setdefault("description", "")

        self._current_event = data
        return self.parse(data, tags=tags or ALL_EVENT_TAGS)

    @staticmethod
    def _listing_page_urls(config, listing_url):
        """Initial listing page URLs: the listing itself + future months
        when month-based pagination is configured.
        """
        urls = [listing_url]
        pagination = config.get("pagination") or {}
        if pagination.get("type") != "month":
            return urls

        template = pagination.get("url_template", "?year={year}&month={month}")
        months_ahead = pagination.get("months_ahead", 2)
        # Some sites (philharmonia) use the season start year in the URL:
        # months before season_start_month belong to the previous year's season
        season_start = pagination.get("season_start_month")

        now = datetime.now()
        year, month = now.year, now.month
        for _ in range(months_ahead):
            month += 1
            if month > 12:
                month, year = 1, year + 1
            url_year = year
            if season_start and month < season_start:
                url_year = year - 1
            urls.append(listing_url + template.format(year=url_year, month=month))
        return urls

    def get_events(self, request_params=None, tags=None, existed_event_ids=None):
        request_params = request_params or {}
        existed_event_ids = list(existed_event_ids) if existed_event_ids else []

        site = request_params.get("site")
        if site is None:
            raise ValueError("'site' key required in request_params.")

        config = self._resolve_config(site)
        listing_url = config["base_url"] + config["listing_url"]

        pagination = config.get("pagination") or {}
        max_pages = pagination.get("max_pages", 10)
        next_selector = (
            pagination.get("next_selector") if pagination.get("type") == "next" else None
        )

        page_urls = self._listing_page_urls(config, listing_url)
        visited = set()
        pages_fetched = 0

        listing_slug = self._slug_from_url(listing_url)
        seen_ids = set()

        while page_urls and pages_fetched < max_pages:
            page_url = page_urls.pop(0)
            if page_url in visited:
                continue
            visited.add(page_url)

            response = self._request_get(page_url)
            if not response:
                # Keep whatever the remaining pages give us
                continue
            pages_fetched += 1

            soup = BeautifulSoup(response.text, "lxml")
            cards = soup.select(config.get("card_selector", "a.event"))
            logger.debug(
                "%s: %s cards on listing page %s (%s)",
                config.get("source", self.source), len(cards), pages_fetched, page_url,
            )

            yield from self._events_from_cards(
                cards, config, site, tags, listing_slug, seen_ids, existed_event_ids
            )

            if next_selector:
                link = soup.select_one(next_selector)
                if link and link.get("href"):
                    page_urls.append(urljoin(config["base_url"], link["href"]))

    def _events_from_cards(
        self, cards, config, site, tags, listing_slug, seen_ids, existed_event_ids
    ):
        for card in cards:
            card_data = self._parse_listing_card(card, config)
            if not card_data or not card_data.get("title"):
                continue

            # Optionally skip cards with no parseable date (announcements,
            # open calls, programme teasers)
            if config.get("require_date"):
                fmt = config.get("date_format", "%d.%m.%Y")
                d_from, d_to, _ = self._parse_date_range(card_data.get("date_str"), fmt)
                if d_from is None and d_to is None:
                    continue

            url = card_data["url"]

            # Pre-compute event_id for dedup (same logic as _id)
            prefix = f"{self.source}-{config['source']}-"
            max_slug = 30 - len(prefix)
            slug = self._slug_from_url(url)
            base_host = urlparse(config.get("base_url", "")).netloc
            url_host = urlparse(url).netloc
            if (slug and slug != listing_slug
                    and url_host == base_host
                    and len(slug) <= max_slug):
                event_id = f"{prefix}{slug}"
            else:
                title = card_data["title"]
                if title and not title[0].isalnum():
                    title = title[2:].strip()
                salt = card_data.get("date_str") or ""
                event_id = f"{prefix}{self._make_short_id(title, max_slug, salt=salt)}"
            if event_id in existed_event_ids or event_id in seen_ids:
                continue
            seen_ids.add(event_id)

            event = self.get_event(
                event_url=url, tags=tags, site=site, card_data=card_data
            )
            if event:
                yield event

    # --- field methods ---

    def _title(self, event_data):
        return add_emoji(event_data.get("title", ""))

    @staticmethod
    def _clean_place(place):
        """Strip list markers ('● Цех') and trailing punctuation ('Барная линия,')."""
        place = re.sub(r"^[^\w«\"']+", "", place)
        return place.strip().rstrip(",.")

    def _adress(self, event_data):
        # Explicit address from the card wins (e.g. off-site events)
        if event_data.get("address"):
            return event_data["address"]
        place = event_data.get("place")
        if place:
            places = self._current_config.get("places", {})
            address = places.get(self._clean_place(place))
            if address:
                return address
        return self._current_config.get("default_address", "")

    def _category(self, event_data):
        category = event_data.get("category")
        if category and self._current_config.get("card_category_detect"):
            category = detect_category(category)
        if category:
            return category
        default = self._current_config.get("default_category")
        if default:
            return default
        title = event_data.get("title", "")
        text = event_data.get("description", "")
        return detect_category(title, text)

    def _default_event_time(self):
        """(hour, minute) to use when the site gives no event time."""
        default = self._current_config.get("default_time")
        if default:
            match = re.match(r"(\d{1,2}):(\d{2})", default)
            if match:
                return int(match.group(1)), int(match.group(2))
        return self.DEFAULT_EVENT_HOUR, 0

    def _date_from(self, event_data):
        date_str = event_data.get("date_str")
        fmt = self._current_config.get("date_format", "%d.%m.%Y")
        date_from, _, time_str = self._parse_date_range(date_str, fmt)

        default_hour, default_minute = self._default_event_time()

        # Default: one week from now at the default event time
        if date_from is None:
            date_from = datetime.now(self.TIMEZONE) + timedelta(weeks=1)
            return date_from.replace(
                hour=default_hour, minute=default_minute, second=0, microsecond=0
            )

        # Time from date string (e.g. "21 февраля, 19:00")
        # or from detail page (e.g. "19:30", "с 19:00", "с 12:00 до 22:00")
        time_str = time_str or event_data.get("time", "")
        match = re.search(r"(\d{1,2}):(\d{2})", time_str) if time_str else None
        if match:
            date_from = date_from.replace(
                hour=int(match.group(1)), minute=int(match.group(2))
            )
        elif date_from.hour == 0 and date_from.minute == 0:
            # Site gave no time — use the default time instead of midnight
            date_from = date_from.replace(hour=default_hour, minute=default_minute)
        return self.TIMEZONE.localize(date_from)

    def _date_to(self, event_data):
        date_str = event_data.get("date_str")
        fmt = self._current_config.get("date_format", "%d.%m.%Y")
        date_from, date_to, time_str = self._parse_date_range(date_str, fmt)

        # Closing time like "с 12:00 до 22:00" from date string or detail page
        time_str = time_str or event_data.get("time", "")
        closing = re.search(r"до\s*(\d{1,2}):(\d{2})", time_str) if time_str else None

        if date_to:
            if closing:
                date_to = date_to.replace(
                    hour=int(closing.group(1)), minute=int(closing.group(2))
                )
            else:
                # End of the last day instead of midnight before it
                date_to = date_to.replace(hour=23, minute=59)
            return self.TIMEZONE.localize(date_to)

        if closing and date_from:
            date_to = date_from.replace(
                hour=int(closing.group(1)), minute=int(closing.group(2))
            )
            return self.TIMEZONE.localize(date_to)

        # No explicit end date — date_from + 2 hours
        return self._date_from(event_data) + timedelta(hours=2)


    def _date_from_to(self, event_data):
        return event_data.get("date_str")

    def _id(self, event_data):
        source = self._current_config.get("source", self.source)
        prefix = f"{self.source}-{source}-"
        max_slug = 30 - len(prefix)

        url = event_data.get("url", "")
        base_url = self._current_config.get("base_url", "")
        base_host = urlparse(base_url).netloc
        url_host = urlparse(url).netloc

        slug = self._slug_from_url(url)
        listing_slug = self._slug_from_url(
            base_url + self._current_config.get("listing_url", "/")
        )

        # Use URL slug only if same domain, unique, and short enough
        if (slug and slug != listing_slug
                and url_host == base_host
                and len(slug) <= max_slug):
            return f"{prefix}{slug}"

        # Otherwise generate from title (+ date, to tell recurring events apart)
        title = event_data.get("title", "")
        # Strip emoji prefix (2 chars: emoji + space)
        if title and not title[0].isalnum():
            title = title[2:].strip()
        salt = event_data.get("date_str") or ""
        return f"{prefix}{self._make_short_id(title, max_slug, salt=salt)}"

    def _url(self, event_data):
        return event_data.get("url", "")

    def _ticket_url(self, event_data):
        return event_data.get("url", "")

    def _place_name(self, event_data):
        default = self._current_config.get("default_place", "")
        place = event_data.get("place")
        if place:
            place = self._clean_place(place)
            if place and place.lower() != default.lower():
                return f"{default}, {place}" if default else place
        return default

    def _full_text(self, event_data):
        return event_data.get("description", "")

    def _post_text(self, event_data):
        return self.prepare_post_text(self._full_text(event_data))

    def _poster_imag(self, event_data):
        image = event_data.get("image")
        if image and not image.startswith("http"):
            base = self._current_config.get("base_url", "")
            return urljoin(base, image)
        return image

    def _price(self, event_data):
        price = event_data.get("price")
        if price is None:
            return "на сайте"
        try:
            return str(int(price)) + "₽"
        except (ValueError, TypeError):
            price = str(price).strip()
            # "1000 р." / "8000 — 10000 руб." → trailing currency word to ₽
            normalized = re.sub(r"\s*р(?:уб\w*)?\.?\s*$", "₽", price, flags=re.IGNORECASE)
            if "₽" in normalized or "руб" in normalized.lower():
                return normalized
            return normalized + "₽"

    def _source(self, event_data):
        return self.source

    def _is_registration_open(self, event_data):
        return True
