"""Scraper de https://www.anthropic.com/news (no tiene RSS).

Las clases CSS del sitio tienen hashes que cambian en cada deploy, así que
nos guiamos por la estructura: cada nota es un `<a href="/news/...">` con un
`<time>` adentro. El listado no trae el cuerpo, así que bajamos la página de
cada nota que entra en la ventana.
"""

import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urljoin

import httpx
from selectolax.lexbor import LexborHTMLParser, LexborNode

from diario.config import FuenteScrape
from diario.fuentes.articulos import descargar_texto
from diario.fuentes.base import ErrorFuente
from diario.modelos import ItemCrudo
from diario.normalizacion import limpiar_espacios

logger = logging.getLogger(__name__)

_MESES = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}  # fmt: skip
# "Oct 6, 2026", "Sept. 23, 2026", "September 23, 2026"
_FECHA = re.compile(r"\b([A-Za-z]{3})[A-Za-z]*\.?\s+(\d{1,2}),\s*(\d{4})\b")


@dataclass(frozen=True, slots=True)
class Tarjeta:
    url: str
    titulo: str
    fecha: datetime
    resumen: str


def traer(fuente: FuenteScrape, cliente: httpx.Client, desde: datetime | None) -> list[ItemCrudo]:
    respuesta = cliente.get(str(fuente.url))
    respuesta.raise_for_status()
    tarjetas = parsear_listado(respuesta.text, base_url=str(respuesta.url))

    items: list[ItemCrudo] = []
    for t in tarjetas:
        if desde is not None and t.fecha < desde:
            continue
        items.append(
            ItemCrudo(
                fuente=fuente.nombre,
                area=fuente.area,
                url=t.url,
                titulo=t.titulo,
                # Si no se puede bajar la nota, queda el resumen del listado.
                contenido=descargar_texto(cliente, t.url) or t.resumen,
                fecha_publicacion=t.fecha,
            )
        )
    return items


def parsear_listado(html: str, base_url: str) -> list[Tarjeta]:
    arbol = LexborHTMLParser(html)
    tarjetas: dict[str, Tarjeta] = {}  # por URL: la misma nota puede aparecer dos veces

    for enlace in arbol.css('a[href^="/news/"]'):
        url = urljoin(base_url, enlace.attributes.get("href") or "")
        if url in tarjetas:
            continue
        titulo = _titulo(enlace)
        fecha = _fecha(enlace)
        if not titulo or fecha is None:
            logger.debug("Tarjeta ignorada (sin título o fecha): %s", url)
            continue
        parrafo = enlace.css_first("p")
        resumen = limpiar_espacios(parrafo.text()) if parrafo is not None else ""
        tarjetas[url] = Tarjeta(url=url, titulo=titulo, fecha=fecha, resumen=resumen)

    if not tarjetas:
        raise ErrorFuente("No se encontró ninguna nota en el listado: ¿cambió el HTML?")
    return list(tarjetas.values())


def _titulo(enlace: LexborNode) -> str:
    nodo = enlace.css_first("h1, h2, h3, h4") or enlace.css_first('[class*="title"]')
    return limpiar_espacios(nodo.text()) if nodo is not None else ""


def _fecha(enlace: LexborNode) -> datetime | None:
    nodo = enlace.css_first("time")
    if nodo is None:
        return None
    # Si algún día agregan el atributo estándar `datetime`, lo preferimos.
    iso = nodo.attributes.get("datetime")
    if iso:
        try:
            fecha = datetime.fromisoformat(iso)
            return fecha if fecha.tzinfo else fecha.replace(tzinfo=UTC)
        except ValueError:
            pass
    return parsear_fecha_en_ingles(nodo.text())


def parsear_fecha_en_ingles(texto: str) -> datetime | None:
    """'Oct 6, 2026' -> 2026-10-06 00:00 UTC. Sin depender del locale del sistema."""
    m = _FECHA.search(texto)
    if m is None:
        return None
    mes = _MESES.get(m.group(1).lower())
    if mes is None:
        return None
    try:
        return datetime(int(m.group(3)), mes, int(m.group(2)), tzinfo=UTC)
    except ValueError:  # ej. "Feb 31"
        return None
