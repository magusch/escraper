"""Site configs for ConfigScraper, grouped by city.

Each entry describes one site with CSS selectors and defaults — no code needed
to add a site. Put a new site into its city module (spb.py, kazan.py, ...) and
set "city" to the city slug (utils.CITY_NAMES). See docs/config_scraper_sites.md
for the full guide and key-by-key reference.
"""

from .kazan import KAZAN_SITES
from .spb import SPB_SITES

# city slug → {site name → config}
SITES_BY_CITY = {
    "spb": SPB_SITES,
    "kazan": KAZAN_SITES,
}

# All sites, flat — site names are unique across cities
SITES = {name: cfg for sites in SITES_BY_CITY.values() for name, cfg in sites.items()}
assert len(SITES) == sum(map(len, SITES_BY_CITY.values())), "duplicate site name"
