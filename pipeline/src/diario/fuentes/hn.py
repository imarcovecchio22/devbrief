"""Fetcher de Hacker News usando la API de búsqueda de Algolia.

Para `hn` pedimos las stories de la ventana con al menos `min_puntaje` puntos:
en la práctica son las que pasaron por la portada, aunque ya hayan salido.
"""

from datetime import UTC, datetime

import httpx
from pydantic import BaseModel, ValidationError

from diario.config import FuenteHn
from diario.fuentes.base import ErrorFuente
from diario.modelos import ItemCrudo
from diario.normalizacion import html_a_texto, limpiar_espacios

URL_API = "https://hn.algolia.com/api/v1/search_by_date"
URL_ITEM_HN = "https://news.ycombinator.com/item?id={id}"

_TAGS = {"hn": "story", "hn_show": "show_hn"}


class _Hit(BaseModel):
    # Solo declaramos lo que usamos; pydantic ignora el resto de los campos.
    objectID: str
    title: str
    url: str | None = None
    points: int | None = None
    created_at_i: int
    story_text: str | None = None


class _Respuesta(BaseModel):
    hits: list[_Hit]


def traer(fuente: FuenteHn, cliente: httpx.Client, desde: datetime) -> list[ItemCrudo]:
    respuesta = cliente.get(
        URL_API,
        params={
            "tags": _TAGS[fuente.tipo],
            "numericFilters": (
                f"points>={fuente.min_puntaje},created_at_i>{int(desde.timestamp())}"
            ),
            # Máximo que permite Algolia; con corridas diarias llegan ~30.
            "hitsPerPage": 1000,
        },
    )
    respuesta.raise_for_status()
    return parsear(respuesta.content, fuente, desde)


def parsear(contenido: bytes, fuente: FuenteHn, desde: datetime | None) -> list[ItemCrudo]:
    try:
        datos = _Respuesta.model_validate_json(contenido)
    except ValidationError as e:
        raise ErrorFuente(f"Respuesta inesperada de Algolia para {fuente.nombre}: {e}") from e

    items: list[ItemCrudo] = []
    for hit in datos.hits:
        fecha = datetime.fromtimestamp(hit.created_at_i, tz=UTC)
        # La API ya filtra, pero lo repetimos para no depender de ella.
        if (hit.points or 0) < fuente.min_puntaje:
            continue
        if desde is not None and fecha < desde:
            continue

        items.append(
            ItemCrudo(
                fuente=fuente.nombre,
                area=fuente.area,
                # "Ask HN" y similares no tienen link externo: usamos la discusión.
                url=hit.url or URL_ITEM_HN.format(id=hit.objectID),
                titulo=limpiar_espacios(hit.title),
                contenido=html_a_texto(hit.story_text or ""),
                fecha_publicacion=fecha,
                senal=hit.points,
            )
        )
    return items
