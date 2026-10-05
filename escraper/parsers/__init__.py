from .base import ALL_EVENT_TAGS
from .timepad import Timepad
from .radario import Radario
from .ticketscloud import Ticketscloud
from .vk import VK
from .qtickets import QTickets
from .mts import MTS
from .culture import Culture
from .tripster import Tripster
from .tg import Telegram
from .yandex import Yandex
from .config_scraper import ConfigScraper
from .kassir import Kassir
from .afisha import Afisha
from .vibe import Vibe



all_parsers = dict(
    timepad=Timepad,
    radario=Radario,
    ticketscloud=Ticketscloud,
    vk=VK,
    mts=MTS,
    cltr=Culture,
    tripster=Tripster,
    tg=Telegram,
    yandex=Yandex,
    config=ConfigScraper,
    kassir=Kassir,
    afisha=Afisha,
    vibe=Vibe,
)
