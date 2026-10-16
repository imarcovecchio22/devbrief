"""Agrupa los items que son la misma noticia.

1. Misma URL canónica -> mismo item, sin excepciones.
2. Títulos muy parecidos en fuentes distintas -> mismo item, con salvaguardas
   para no fusionar cosas distintas que se titulan parecido (ver `_similares`).

Cada grupo conserva todas sus apariciones: que una noticia esté en varias
fuentes es señal de relevancia.

`existentes` son items ya guardados en la base. Si un grupo nuevo coincide con
uno, adopta su URL canónica: así la base lo trata como una aparición más del
mismo item (INSERT ... ON CONFLICT) en vez de crear uno nuevo.
"""

import logging
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime

from rapidfuzz import fuzz

from diario.modelos import ItemCrudo
from diario.normalizacion import canonicalizar_url, es_release_github

logger = logging.getLogger(__name__)

UMBRAL_SIMILITUD = 90  # 0-100, sobre títulos normalizados
MIN_PALABRAS = 3  # títulos más cortos son demasiado ambiguos para comparar

# \u2013 es el guion largo que HN suele usar en "Show HN: X \u2013 Y".
_PREFIJOS_HN = re.compile(r"^(show|ask|launch|tell) hn\s*[:\-\u2013]\s*", re.IGNORECASE)
_NO_ALFANUMERICO = re.compile(r"[\W_]+")
_NUMEROS = re.compile(r"\d+(?:\.\d+)*")


@dataclass(frozen=True, slots=True)
class Referencia:
    """Lo mínimo de un item ya guardado que hace falta para compararlo."""

    url_canonica: str
    titulo: str
    fuentes: frozenset[str]


@dataclass(slots=True)
class Grupo:
    url_canonica: str
    apariciones: list[ItemCrudo] = field(default_factory=list)

    @property
    def representante(self) -> ItemCrudo:
        # El que trae más texto: si HN linkea un post de un blog que también
        # leemos por RSS, nos quedamos con el título y el cuerpo del blog.
        return max(self.apariciones, key=lambda i: len(i.contenido))

    @property
    def titulo(self) -> str:
        return self.representante.titulo

    @property
    def contenido(self) -> str:
        return self.representante.contenido

    @property
    def fecha_publicacion(self) -> datetime | None:
        fechas = [i.fecha_publicacion for i in self.apariciones if i.fecha_publicacion]
        return min(fechas, default=None)

    @property
    def fuentes(self) -> frozenset[str]:
        return frozenset(i.fuente for i in self.apariciones)

    @property
    def es_release(self) -> bool:
        return any(es_release_github(i.url) for i in self.apariciones)

    def agregar(self, items: Iterable[ItemCrudo]) -> None:
        # Una fuente cuenta una sola vez por grupo (un feed puede repetir entradas).
        for item in items:
            if item.fuente not in self.fuentes:
                self.apariciones.append(item)


def normalizar_titulo(titulo: str) -> str:
    t = _PREFIJOS_HN.sub("", titulo.strip())
    return _NO_ALFANUMERICO.sub(" ", t.casefold()).strip()


def agrupar(items: Iterable[ItemCrudo], existentes: Sequence[Referencia] = ()) -> list[Grupo]:
    por_url: dict[str, Grupo] = {}
    for item in items:
        try:
            url = canonicalizar_url(item.url)
        except ValueError as e:
            logger.warning("Item descartado de %s: %s", item.fuente, e)
            continue
        por_url.setdefault(url, Grupo(url)).agregar([item])

    resultado: list[Grupo] = []
    for grupo in por_url.values():
        igual = next((g for g in resultado if _grupos_similares(grupo, g)), None)
        if igual is not None:
            logger.debug("Fusionado por título: %r con %r", grupo.titulo, igual.titulo)
            igual.agregar(grupo.apariciones)
            continue

        ref = next((r for r in existentes if _similar_a_referencia(grupo, r)), None)
        if ref is not None and ref.url_canonica != grupo.url_canonica:
            logger.debug("Coincide con item existente: %r -> %s", grupo.titulo, ref.url_canonica)
            grupo.url_canonica = ref.url_canonica
        resultado.append(grupo)
    return resultado


def _grupos_similares(a: Grupo, b: Grupo) -> bool:
    return _similares(a.titulo, a.fuentes, a.es_release, b.titulo, b.fuentes, b.es_release)


def _similar_a_referencia(g: Grupo, r: Referencia) -> bool:
    if g.url_canonica == r.url_canonica:
        return True
    ref_es_release = es_release_github(r.url_canonica)
    return _similares(g.titulo, g.fuentes, g.es_release, r.titulo, r.fuentes, ref_es_release)


def _similares(
    titulo_a: str,
    fuentes_a: frozenset[str],
    release_a: bool,
    titulo_b: str,
    fuentes_b: frozenset[str],
    release_b: bool,
) -> bool:
    # Los releases de un mismo repo se titulan casi igual: no se fusionan nunca.
    if release_a or release_b:
        return False
    # Una misma fuente no publica dos veces la misma noticia con URLs distintas;
    # si los títulos se parecen, son entregas distintas ("Parte 1", "Parte 2").
    if fuentes_a & fuentes_b:
        return False

    a, b = normalizar_titulo(titulo_a), normalizar_titulo(titulo_b)
    if len(a.split()) < MIN_PALABRAS or len(b.split()) < MIN_PALABRAS:
        return False
    # "Python 3.16 alpha 1" vs "alpha 2", "GPT-5" vs "GPT-4": casi iguales, distintos.
    if set(_NUMEROS.findall(a)) != set(_NUMEROS.findall(b)):
        return False
    return fuzz.token_sort_ratio(a, b) >= UMBRAL_SIMILITUD
