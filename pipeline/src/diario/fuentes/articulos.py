"""Descarga y extracción del texto principal de un artículo cualquiera.

Se usa para los items que llegan sin contenido (la mayoría de HN solo trae
título y link) y para el cuerpo de las notas de Anthropic News.
"""

import logging
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit

import httpx
from selectolax.lexbor import LexborHTMLParser

from diario.normalizacion import limpiar_espacios

logger = logging.getLogger(__name__)

TIMEOUT_SEGUNDOS = 10.0
MAX_BYTES = 3_000_000

# Partes de una página que nunca son el artículo.
_TAGS_RUIDO = [
    "script", "style", "noscript", "template", "svg", "iframe",
    "nav", "header", "footer", "aside", "form", "button",
]  # fmt: skip

# Páginas que no tiene sentido bajar: discusiones de HN (no son el artículo).
_HOSTS_IGNORADOS = {"news.ycombinator.com"}


def extraer_texto_principal(html: str) -> str:
    """Texto del cuerpo de la página: <article>, si no <main>, si no <body>."""
    if not html.strip():
        return ""
    arbol = LexborHTMLParser(html)
    arbol.strip_tags(_TAGS_RUIDO)
    nodo = (
        arbol.css_first("article")
        or arbol.css_first("main")
        or arbol.css_first('[role="main"]')
        or arbol.body
    )
    return limpiar_espacios(nodo.text(separator=" ")) if nodo is not None else ""


def descargar_texto(cliente: httpx.Client, url: str) -> str:
    """Devuelve el texto del artículo, o "" si no se pudo (nunca lanza)."""
    if (urlsplit(url).hostname or "") in _HOSTS_IGNORADOS:
        return ""
    try:
        respuesta = cliente.get(url, timeout=TIMEOUT_SEGUNDOS)
        respuesta.raise_for_status()
    except httpx.HTTPError as e:
        # Muchos sitios bloquean clientes que no son navegadores: es esperable.
        logger.debug("No se pudo bajar %s: %s", url, e)
        return ""

    tipo = respuesta.headers.get("content-type", "")
    if "html" not in tipo:
        logger.debug("Se ignora %s: no es HTML (%s)", url, tipo)
        return ""
    if len(respuesta.content) > MAX_BYTES:
        logger.debug("Se ignora %s: demasiado grande", url)
        return ""
    return extraer_texto_principal(respuesta.text)


def descargar_textos(cliente: httpx.Client, urls: Sequence[str], *, hilos: int = 8) -> list[str]:
    """Descarga en paralelo. Devuelve los textos en el mismo orden que `urls`."""
    with ThreadPoolExecutor(max_workers=hilos) as pool:
        return list(pool.map(lambda u: descargar_texto(cliente, u), urls))
