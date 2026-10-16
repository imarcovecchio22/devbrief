"""Fetcher para feeds RSS 2.0 y Atom (incluye los releases.atom de GitHub)."""

import re
import time
from datetime import UTC, datetime
from typing import Any

import feedparser
import httpx

from diario.config import FuenteRss
from diario.fuentes.base import ErrorFuente
from diario.modelos import ItemCrudo
from diario.normalizacion import (
    es_release_github,
    html_a_texto,
    limpiar_espacios,
    titulo_de_release,
)


def traer(fuente: FuenteRss, cliente: httpx.Client, desde: datetime | None) -> list[ItemCrudo]:
    respuesta = cliente.get(str(fuente.url))
    respuesta.raise_for_status()
    return parsear(respuesta.content, fuente, desde)


def parsear(contenido: bytes, fuente: FuenteRss, desde: datetime | None) -> list[ItemCrudo]:
    """Convierte el XML del feed en items. Si hay `desde`, descarta los más viejos."""
    feed = feedparser.parse(contenido)
    # `bozo` marca cualquier irregularidad del XML; solo es fatal si no salió nada.
    if feed.bozo and not feed.entries:
        raise ErrorFuente(f"Feed inválido en {fuente.nombre}: {feed.bozo_exception}")

    items: list[ItemCrudo] = []
    for entrada in feed.entries:
        url = entrada.get("link")
        titulo = limpiar_espacios(entrada.get("title", ""))
        if not url or not titulo:
            continue

        fecha = _fecha(entrada)
        if desde is not None and fecha is not None and fecha < desde:
            continue

        if es_release_github(url):
            # Muchos repos titulan solo con la versión ("0.13.1"): sin el
            # nombre del proyecto el título no le dice nada al LLM ni al lector.
            titulo = titulo_de_release(titulo, _proyecto(fuente.nombre))

        items.append(
            ItemCrudo(
                fuente=fuente.nombre,
                area=fuente.area,
                url=url,
                titulo=titulo,
                contenido=html_a_texto(_cuerpo_html(entrada)),
                fecha_publicacion=fecha,
            )
        )
    return items


def _proyecto(nombre_fuente: str) -> str:
    # "Claude Code releases" -> "Claude Code"
    return re.sub(r"\s+releases?$", "", nombre_fuente, flags=re.IGNORECASE)


def _fecha(entrada: Any) -> datetime | None:
    # Algunos feeds (releases de GitHub, Real Python) solo traen `updated`.
    t: time.struct_time | None = entrada.get("published_parsed") or entrada.get("updated_parsed")
    if t is None:
        return None
    # feedparser ya normaliza a UTC; struct_time no tiene zona, se la agregamos.
    return datetime(*t[:6], tzinfo=UTC)


def _cuerpo_html(entrada: Any) -> str:
    # `content` suele ser el artículo completo; `summary`, un extracto.
    contenidos = entrada.get("content") or []
    if contenidos:
        return str(contenidos[0].get("value", ""))
    return str(entrada.get("summary", ""))
