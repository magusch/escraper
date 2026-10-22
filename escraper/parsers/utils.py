import re


STRPTIME = "%Y-%m-%dT%H:%M:%S%z"

# Keyword → category mapping for automatic detection from title/text.
# Checked in order; first match wins. Keys are lowercase substrings.
CATEGORY_KEYWORDS = {
    "концерт": "концерты",
    "music": "концерты",
    "live": "концерты",
    "dj": "концерты",
    "джаз": "концерты",
    "jazz": "концерты",
    "рок": "концерты",
    "rock": "концерты",
    "спектакль": "театр",
    "театр": "театр",
    "перформанс": "театр",
    "опер": "театр",
    "балет": "театр",
    "кино": "кино",
    "фильм": "кино",
    "показ": "кино",
    "лекция": "лекции",
    "лекторий": "лекции",
    "лектор": "лекции",
    "воркшоп": "мастер-классы",
    "мастер-класс": "мастер-классы",
    "workshop": "мастер-классы",
    "выставк": "выставки",
    "экспозиц": "выставки",
    "exhibition": "выставки",
    "экскурси": "экскурсии",
    "прогулк": "экскурсии",
    "фестивал": "фестивали",
    "festival": "фестивали",
    "ярмарк": "ярмарки",
    "маркет": "ярмарки",
    "market": "ярмарки",
    "вечеринк": "вечеринки",
    "party": "вечеринки",
    "детск": "детям",
    "для детей": "детям",
    "семейн": "детям",
    "йога": "спорт",
    "бег": "спорт",
    "забег": "спорт",
}


def detect_category(title, text=""):
    """Detect event category from title and text by keyword matching.

    Returns category string or empty string if no match.
    Title is checked first (higher priority), then text.
    """
    for source in (title, text):
        lower = source.lower()
        for keyword, category in CATEGORY_KEYWORDS.items():
            if keyword in lower:
                return category
    return ""


DEFAULT_CITY_NAME = "Санкт-Петербург"
CITY_NAMES = {
    "spb": "Санкт-Петербург",
    "sankt-peterburg": "Санкт-Петербург",
    "saint-petersburg": "Санкт-Петербург",
    "msk": "Москва",
    "moscow": "Москва",
    "kzn": "Казань",
    "kazan": "Казань",
    "ekb": "Екатеринбург",
    "ekaterinburg": "Екатеринбург",
    "nsk": "Новосибирск",
    "novosibirsk": "Новосибирск",
    "nn": "Нижний Новгород",
    "nnov": "Нижний Новгород",
    "nizhniy-novgorod": "Нижний Новгород",
    "sochi": "Сочи",
    "krd": "Краснодар",
    "krasnodar": "Краснодар",
}


def city_name(city):
    """Resolve a city slug ("kzn", "kazan"), domain ("kzn.kassir.ru") or
    Russian name ("Казань") to the Russian city name.

    Returns DEFAULT_CITY_NAME for an empty value and None for an unknown slug.
    """
    if not city:
        return DEFAULT_CITY_NAME
    city = str(city).strip()
    if re.search(r"[А-Яа-яЁё]", city):
        return city
    slug = city.lower().split(".")[0]
    return CITY_NAMES.get(slug)


def require_city_name(city, source):
    """Like ``city_name`` but raises ValueError for a city that can't be resolved.

    An empty value means the default city (Санкт-Петербург).
    """
    name = city_name(city)
    if name is None:
        raise ValueError(
            f"{source}: unknown city {city!r}; known slugs: {', '.join(sorted(CITY_NAMES))}"
        )
    return name


def strip_city(address, city=None):
    """Remove the requested city from an address.

    "г. Казань, ул. Баумана, 1" → "ул. Баумана, 1"
    "ул. Баумана, 1, Казань"    → "ул. Баумана, 1"

    ``city`` is anything ``city_name`` accepts; defaults to Санкт-Петербург.
    Other cities are kept, so an out-of-town venue still shows its city.
    """
    if not address:
        return address or ""
    name = city_name(city)
    if not name:
        return address.strip()
    city_re = r"(?:г\.?\s*)?" + re.escape(name)
    address = re.sub(r"^\s*(?:Россия,\s*)?" + city_re + r"\s*,\s*", "", address, flags=re.IGNORECASE)
    address = re.sub(r",\s*" + city_re + r"\s*(?:,\s*Россия)?\s*$", "", address, flags=re.IGNORECASE)
    return address.strip()
