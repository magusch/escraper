"""Parser for the curated afisha of kazan-kremlin.ru (Музей-заповедник «Казанский Кремль»).

Site-specific: the site is Next.js on top of WordPress, and all fields below
are this site's own ACF setup — another WordPress site would need its own parser.

Requests (no cookies/tokens needed):
  1. GET  admin.kazan-kremlin.ru/wp-json/custom/v1/afisha-filters/?type=<t>
     — the list the site itself shows: already without past items.
  2. GET  admin.kazan-kremlin.ru/wp-json/wp/v2/<t>?include=<ids>&_fields=id,content
     — full description text (afisha-filters has none).

Dates are the hard part. ``common_fields.dates[].manual_text`` is what the
editors actually type ("с 11 по 29 декабря 2026 года", "15 октября, 19 ноября
в 11:00") and wins over the structured ``date_period`` / ``date_list``, which
for events is often just the publish date. Standing offers ("По
предварительной записи", "Каждую субботу") have no concrete date → skipped.

Rules:
  * exhibitions: real ``date_period`` (start != end); virtual ones skipped;
    long exhibitions are kept;
  * events: concrete dates only; spans longer than MAX_EVENT_DAYS skipped.

Ticket sessions/prices for the box office live in the TNCloud parser
(site "kremlin"); this parser covers exhibitions and curated events.
"""

import html
import logging
import re
from datetime import datetime, timedelta

from bs4 import BeautifulSoup

from escraper.parsers.base import BaseParser, ALL_EVENT_TAGS
from escraper.parsers.config_scraper import MONTHS_RU
from escraper.parsers.utils import detect_category
from escraper.emoji import add_emoji

logger = logging.getLogger(__name__)

API_BASE = "https://admin.kazan-kremlin.ru/wp-json"
PUBLIC_BASE = "https://kazan-kremlin.ru"

MAX_EVENT_DAYS = 60
DEFAULT_TIME = (10, 0)            # museums open at 10
EXHIBITION_CLOSE = (18, 0)        # typical closing time for date_to
DEFAULT_DURATION_MIN = 120

DEFAULT_PLACE = "Казанский Кремль"
DEFAULT_ADDRESS = "территория Кремль"

# WordPress museum post ID → (short name, address). The museum posts carry no
# address field; addresses are from the Kremlin box office venues.
MUSEUMS = {
    807: ("Выставочные залы Присутственных мест", "территория Кремль, 5"),
    803: ("Музей истории Благовещенского собора", "территория Кремль, 2"),
    800: ("Выставочный зал «Манеж»", "территория Кремль, 11"),
    798: ("Музей исламской культуры", "территория Кремль, 13"),
    795: ("Центр «Эрмитаж-Казань»", "территория Кремль, 12"),
    786: ("Музей Пушечного двора", "территория Кремль, 14"),
    778: ("Музей естественной истории Татарстана", "территория Кремль, 12"),
    319: ("Музей истории государственности Татарстана", "территория Кремль, 1А"),
    312: ("Музей Спасской башни", "территория Кремль, 8"),
}

# manual_text without a concrete date
NO_DATE_RE = re.compile(
    r"кажд|ежедневн|по предварительн|уточня|виртуальн|по записи|по заявк", re.IGNORECASE
)
MONTH_WORD = r"([а-яё]+)"
RANGE_RE = re.compile(
    r"(?:с\s+)?(\d{1,2})(?:\s+" + MONTH_WORD + r")?(?:\s+(\d{4}))?(?:\s+года?)?"
    r"\s*(?:по|до|[-–—])\s*(\d{1,2})\s+" + MONTH_WORD + r"(?:\s+(\d{4}))?",
    re.IGNORECASE,
)
DAY_MONTH_RE = re.compile(r"(?<!\d)(\d{1,2})\s+" + MONTH_WORD + r"(?:\s+(\d{4}))?", re.IGNORECASE)
TIME_RE = re.compile(r"(?<![\d.])(\d{1,2})[:.](\d{2})(?![\d.])")
DURATION_RE = re.compile(r"(\d{2,3})\s*мин", re.IGNORECASE)


def _month(word):
    word = (word or "").lower()
    for prefix, num in MONTHS_RU.items():
        if word.startswith(prefix):
            return num
    return None


def _make_date(day, month, year, today):
    """Date with the year inferred: no year → this year, or next year when
    that would be more than half a year in the past (December → January)."""
    explicit = year is not None
    year = int(year) if explicit else today.year
    try:
        result = datetime(year, month, int(day))
    except ValueError:
        return None
    if not explicit and (today - result).days > 180:
        result = result.replace(year=year + 1)
    return result


def parse_manual_text(text, today):
    """Concrete dates from the editors' free text.

    Returns ("range", start, end) | ("list", [dates]) | None.
    Times are not handled here (see _times).
    """
    if not text:
        return None
    text = html.unescape(text).replace("\xa0", " ").strip()
    if not text or NO_DATE_RE.search(text):
        return None

    match = RANGE_RE.search(text)
    if match:
        d1, m1, y1, d2, m2, y2 = match.groups()
        month2 = _month(m2)
        month1 = _month(m1) if m1 else month2
        if month1 and month2:
            end = _make_date(d2, month2, y2, today)
            start = _make_date(d1, month1, y1 or y2, today)
            if start and end:
                if start > end:  # "24 декабря – 15 января" without years
                    start = start.replace(year=start.year - 1)
                return ("range", start, end)

    dates = []
    for day, month_word, year in DAY_MONTH_RE.findall(text):
        month = _month(month_word)
        if month:
            date = _make_date(day, month, year or None, today)
            if date:
                dates.append(date)
    if dates:
        return ("list", sorted(set(dates)))
    return None


def _times(*texts):
    """All HH:MM / HH.MM found in the texts, in order."""
    found = []
    for text in texts:
        for h, m in TIME_RE.findall(html.unescape(text or "")):
            if int(h) < 24 and int(m) < 60:
                found.append((int(h), int(m)))
    return found


def _parse_dmy(value):
    try:
        return datetime.strptime(value, "%d/%m/%Y")
    except (TypeError, ValueError):
        return None


class KazanKremlin(BaseParser):
    name = "kazan_kremlin"
    source = "KREMLIN"
    REQUEST_DELAY = 0.5
    TYPES = ("exhibition", "event")

    def __init__(self, use_proxy=True):
        super().__init__(use_proxy=use_proxy)

    def _now(self):
        """Naive Moscow 'now' (overridden in tests)."""
        return datetime.now(self.TIMEZONE).replace(tzinfo=None)

    # ------------------------------------------------------------- requests
    def _get_json(self, url, params=None):
        response = self._request_get(url, params=params, headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json, text/plain, */*",
            "Origin": PUBLIC_BASE,
            "Referer": PUBLIC_BASE + "/",
        })
        if not response:
            return None
        try:
            return response.json()
        except ValueError as e:
            logger.error("KREMLIN: bad JSON from %s: %s", url, e)
            return None

    def _fetch_list(self, post_type):
        """All items of the site's own afisha list (paginated)."""
        items, page = [], 1
        while True:
            data = self._get_json(
                f"{API_BASE}/custom/v1/afisha-filters/",
                params={"type": post_type, "per_page": 100, "page": page},
            )
            if not data:
                break
            items.extend(data.get("data") or [])
            total_pages = (data.get("pagination") or {}).get("total_pages") or 1
            if page >= total_pages or page >= 10:
                break
            page += 1
        return items

    def _fetch_contents(self, post_type, ids):
        """{post id: description text} — one request per 100 ids."""
        contents = {}
        ids = list(ids)
        for i in range(0, len(ids), 100):
            chunk = ids[i:i + 100]
            data = self._get_json(
                f"{API_BASE}/wp/v2/{post_type}",
                params={"include": ",".join(map(str, chunk)), "per_page": 100,
                        "_fields": "id,content"},
            )
            for post in data or []:
                rendered = (post.get("content") or {}).get("rendered") or ""
                contents[post.get("id")] = self._html_to_text(rendered)
        return contents

    # --------------------------------------------------------------- dates
    def _dates(self, item, post_type, today):
        """(start, end, kind) for an item or None when it has no usable dates.

        start/end are naive datetimes with times applied. kind is
        "period" (exhibition/range) or "list".
        """
        fields = item.get("common_fields") or {}
        time_text = fields.get("time") or ""
        for entry in fields.get("dates") or []:
            manual = entry.get("manual_text") or ""
            period = entry.get("date_period") or {}
            p_start, p_end = _parse_dmy(period.get("start")), _parse_dmy(period.get("end"))

            if post_type == "exhibition":
                if p_start and p_end and p_end > p_start:
                    start = p_start.replace(hour=DEFAULT_TIME[0], minute=DEFAULT_TIME[1])
                    end = p_end.replace(hour=EXHIBITION_CLOSE[0], minute=EXHIBITION_CLOSE[1])
                    return start, end, "period"
                parsed = parse_manual_text(manual, today)
                if parsed and parsed[0] == "range":
                    start = parsed[1].replace(hour=DEFAULT_TIME[0], minute=DEFAULT_TIME[1])
                    end = parsed[2].replace(hour=EXHIBITION_CLOSE[0], minute=EXHIBITION_CLOSE[1])
                    return start, end, "period"
                continue

            # events: manual_text first, structured fields only as a fallback
            if manual.strip():
                parsed = parse_manual_text(manual, today)
                if parsed is None:
                    continue  # "По предварительной записи", "Каждую субботу"…
            else:
                date_list = [_parse_dmy(d.get("date")) for d in entry.get("date_list") or []]
                date_list = sorted({d for d in date_list if d})
                if date_list and entry.get("date_type") == "DATE_LIST":
                    parsed = ("list", date_list)
                elif p_start and p_end and p_end > p_start:
                    parsed = ("range", p_start, p_end)
                else:
                    continue  # start == end: publish date, not an event date

            times = _times(manual, time_text)
            start_h, start_m = times[0] if times else DEFAULT_TIME
            if len(times) >= 2 and not _times(manual) and len(_times(time_text)) >= 2:
                end_hm = times[1]            # "с 14:00-16:00"
            else:
                end_hm = None
            duration = DURATION_RE.search(time_text)
            duration = int(duration.group(1)) if duration else DEFAULT_DURATION_MIN

            if parsed[0] == "range":
                first, last = parsed[1], parsed[2]
            else:
                upcoming = [d for d in parsed[1] if d.date() >= today.date()]
                if not upcoming:
                    return None
                first, last = upcoming[0], upcoming[-1]

            start = first.replace(hour=start_h, minute=start_m)
            if end_hm:
                end = last.replace(hour=end_hm[0], minute=end_hm[1])
            else:
                end = last.replace(hour=start_h, minute=start_m) + timedelta(minutes=duration)
            return start, end, parsed[0]
        return None

    # ------------------------------------------------------------ interface
    def get_event(self, event_id=None, post_type=None, tags=None):
        """One item by WordPress post id; post_type "exhibition" or "event"."""
        if event_id is None:
            raise ValueError("'event_id' required.")
        if post_type not in self.TYPES:
            raise ValueError(f"'post_type' must be one of {self.TYPES}.")
        for event in self.get_events(request_params={"types": [post_type]}, tags=tags):
            if str(event.id) == f"{self.source}-{event_id}":
                return event
        return None

    def get_events(self, request_params=None, tags=None, existed_event_ids=None):
        """Current exhibitions and dated events of kazan-kremlin.ru.

        Parameters
        ----------
        request_params : dict
            types : list, default ["exhibition", "event"]
            max_event_days : int, default 60 — longer events are skipped
                (exhibitions are never skipped for length).
        tags : list, optional
        existed_event_ids : list, optional
        """
        request_params = request_params or {}
        tags = tags or ALL_EVENT_TAGS
        existed = set(existed_event_ids) if existed_event_ids else set()
        types = request_params.get("types") or self.TYPES
        max_days = request_params.get("max_event_days", MAX_EVENT_DAYS)
        today = self._now()

        for post_type in types:
            items = self._fetch_list(post_type)
            selected = []
            for item in items:
                event_id = f"{self.source}-{item.get('id')}"
                if event_id in existed:
                    continue
                fields = item.get("common_fields") or {}
                category = ((fields.get("category") or {}).get("name") or "")
                if "виртуал" in category.lower():
                    continue
                dates = self._dates(item, post_type, today)
                if dates is None:
                    logger.debug("KREMLIN: %s %s has no concrete dates", post_type, item.get("id"))
                    continue
                start, end, _ = dates
                if end.date() < today.date():
                    continue
                if post_type == "event" and (end.date() - start.date()).days + 1 > max_days:
                    logger.debug("KREMLIN: event %s spans > %d days", item.get("id"), max_days)
                    continue
                selected.append((item, start, end))

            contents = self._fetch_contents(post_type, [i["id"] for i, _, _ in selected])
            for item, start, end in selected:
                try:
                    yield self.parse({
                        "item": item,
                        "post_type": post_type,
                        "start": start,
                        "end": end,
                        "text": contents.get(item["id"], ""),
                    }, tags=tags)
                except Exception as e:  # one broken item must not stop the feed
                    logger.warning("KREMLIN: skip %s %s: %s", post_type, item.get("id"), e)

    # -------------------------------------------------------------- helpers
    @staticmethod
    def _html_to_text(rendered):
        soup = BeautifulSoup(rendered, "lxml")
        for br in soup.find_all("br"):
            br.replace_with("\n")
        blocks = [el.get_text(" ", strip=True) for el in soup.find_all(["p", "h2", "h3", "h4", "li"])]
        text = "\n".join(b for b in blocks if b) or soup.get_text(" ", strip=True)
        text = re.sub(r"[ \t\xa0]+", " ", text)
        return re.sub(r"\n\s*\n+", "\n", text).strip()

    @staticmethod
    def _fields(event_data):
        return event_data["item"].get("common_fields") or {}

    def _museum(self, event_data):
        museums = self._fields(event_data).get("museum") or []
        if not museums:
            return None, None
        post = museums[0] or {}
        name, address = MUSEUMS.get(post.get("ID"), (None, None))
        return name or html.unescape(post.get("post_title") or "") or None, address

    # --------------------------------------------------------------- fields
    def _title(self, event_data):
        title = html.unescape(event_data["item"].get("title") or "")
        return add_emoji(re.sub(r"\s+", " ", title).strip())

    def _full_text(self, event_data):
        return event_data.get("text") or html.unescape(event_data["item"].get("excerpt") or "")

    def _post_text(self, event_data):
        return self.prepare_post_text(self._full_text(event_data))

    def _id(self, event_data):
        return f"{self.source}-{event_data['item'].get('id')}"

    def _url(self, event_data):
        # admin.kazan-kremlin.ru/events/<slug>/ → kazan-kremlin.ru/events/<slug>
        link = event_data["item"].get("permalink") or ""
        return link.replace("https://admin.kazan-kremlin.ru", PUBLIC_BASE).rstrip("/")

    def _ticket_url(self, event_data):
        link = self._fields(event_data).get("ticket_link") or {}
        return link.get("url") if isinstance(link, dict) else None

    def _date_from(self, event_data):
        return self.TIMEZONE.localize(event_data["start"])

    def _date_to(self, event_data):
        return self.TIMEZONE.localize(event_data["end"])

    def _date_from_to(self, event_data):
        start, end = event_data["start"], event_data["end"]
        if start.date() == end.date():
            return f"{start:%d.%m.%Y %H:%M}–{end:%H:%M}"
        return f"{start:%d.%m.%Y} – {end:%d.%m.%Y}"

    def _place_name(self, event_data):
        name, _ = self._museum(event_data)
        return f"{DEFAULT_PLACE}, {name}" if name else DEFAULT_PLACE

    def _adress(self, event_data):
        _, address = self._museum(event_data)
        return address or DEFAULT_ADDRESS

    def _category(self, event_data):
        if event_data["post_type"] == "exhibition":
            return "выставки"
        name = (self._fields(event_data).get("category") or {}).get("name") or ""
        return (detect_category(name)
                or detect_category(html.unescape(event_data["item"].get("title") or ""),
                                   self._full_text(event_data)))

    def _poster_imag(self, event_data):
        banner = self._fields(event_data).get("banner") or {}
        return banner.get("url") if isinstance(banner, dict) else None

    def _price(self, event_data):
        raw = html.unescape(self._fields(event_data).get("price") or "").strip()
        if not raw:
            return "на сайте"
        if re.search(r"бесплат|свободн", raw, re.IGNORECASE):
            return "бесплатно"
        values = sorted({int(v) for v in re.findall(r"\d+", raw) if int(v) >= 50})
        if not values:
            return raw
        if len(values) == 1:
            return f"{values[0]}₽"
        return f"{values[0]} - {values[-1]}₽"

    def _source(self, event_data):
        return self.source

    def _is_registration_open(self, event_data):
        return True
