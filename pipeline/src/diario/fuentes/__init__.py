"""Fetchers por tipo de fuente. `traer_items` elige el que corresponde."""

from collections.abc import Callable
from datetime import datetime
from urllib.parse import urlsplit

import httpx

from diario.config import Fuente, FuenteHn, FuenteRss, FuenteScrape
from diario.fuentes import anthropic_news, hn, rss
from diario.fuentes.base import ErrorFuente, FuenteNoSoportada, crear_cliente
from diario.modelos import ItemCrudo

__all__ = ["ErrorFuente", "FuenteNoSoportada", "crear_cliente", "tiene_fetcher", "traer_items"]

type _Scraper = Callable[[FuenteScrape, httpx.Client, datetime | None], list[ItemCrudo]]

# Cada sitio sin RSS necesita su propio scraper, elegido por host.
_SCRAPERS: dict[str, _Scraper] = {
    "www.anthropic.com": anthropic_news.traer,
    "anthropic.com": anthropic_news.traer,
}


def _scraper_para(fuente: FuenteScrape) -> _Scraper | None:
    return _SCRAPERS.get(urlsplit(str(fuente.url)).hostname or "")


def tiene_fetcher(fuente: Fuente) -> bool:
    match fuente:
        case FuenteRss() | FuenteHn():
            return True
        case FuenteScrape():
            return _scraper_para(fuente) is not None
        case _:
            return False


def traer_items(fuente: Fuente, cliente: httpx.Client, desde: datetime) -> list[ItemCrudo]:
    """Trae los items de una fuente publicados desde `desde`.

    Puede lanzar `httpx.HTTPError` o `ErrorFuente`: el que llama decide
    si loguea y sigue con las demás.
    """
    match fuente:
        case FuenteRss():
            return rss.traer(fuente, cliente, desde)
        case FuenteHn():
            return hn.traer(fuente, cliente, desde)
        case FuenteScrape() if (scraper := _scraper_para(fuente)) is not None:
            return scraper(fuente, cliente, desde)
        case _:
            raise FuenteNoSoportada(f"Tipo {fuente.tipo!r} sin fetcher ({fuente.nombre})")
