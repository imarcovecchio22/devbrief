"""Normalización de items: URL canónica, HTML a texto plano y recorte.

La URL canónica es la identidad de un item en la base (columna `url_canonica`),
así que estas reglas definen qué cuenta como "el mismo artículo". La URL
original se guarda aparte, en `item_fuentes`, para linkear.
"""

import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from selectolax.lexbor import LexborHTMLParser

# Parámetros de query que solo sirven para tracking y no cambian el contenido.
_PARAMS_TRACKING = frozenset(
    {"fbclid", "gclid", "dclid", "msclkid", "mc_cid", "mc_eid", "ref", "ref_src"}
)
_PREFIJOS_TRACKING = ("utm_",)

_PUERTOS_DEFAULT = {"http": 80, "https": 443}

_ESPACIOS = re.compile(r"\s+")

# Tags cuyo contenido no es texto legible.
_TAGS_DESCARTABLES = ["script", "style", "noscript", "template", "svg", "iframe"]


def _es_tracking(param: str) -> bool:
    p = param.lower()
    return p in _PARAMS_TRACKING or p.startswith(_PREFIJOS_TRACKING)


def canonicalizar_url(url: str) -> str:
    """Devuelve una forma estable de la URL para comparar items entre fuentes.

    - esquema http/https -> https; host en minúscula, sin `www.` ni puerto default
    - sin fragmento (#...) ni parámetros de tracking; el resto, ordenado
    - sin `/` final en el path (salvo la raíz)
    """
    partes = urlsplit(url.strip())
    esquema = partes.scheme.lower()
    if esquema not in ("http", "https"):
        raise ValueError(f"URL no soportada (esquema {esquema!r}): {url!r}")
    if not partes.hostname:
        raise ValueError(f"URL sin host: {url!r}")

    host = partes.hostname.lower().removeprefix("www.")
    # partes.port lanza ValueError si el puerto no es numérico: lo dejamos subir.
    if partes.port is not None and partes.port != _PUERTOS_DEFAULT[esquema]:
        host = f"{host}:{partes.port}"

    path = partes.path or "/"
    if len(path) > 1:
        path = path.rstrip("/")

    query = urlencode(
        sorted(
            (k, v)
            for k, v in parse_qsl(partes.query, keep_blank_values=True)
            if not _es_tracking(k)
        )
    )

    return urlunsplit(("https", host, path, query, ""))


def limpiar_espacios(texto: str) -> str:
    """Colapsa cualquier secuencia de espacios, tabs o saltos de línea en uno solo."""
    return _ESPACIOS.sub(" ", texto).strip()


def html_a_texto(html: str) -> str:
    """Extrae el texto legible de un fragmento HTML, con entidades decodificadas."""
    if not html.strip():
        return ""
    arbol = LexborHTMLParser(html)
    arbol.strip_tags(_TAGS_DESCARTABLES)
    nodo = arbol.body or arbol.root
    texto = nodo.text(separator=" ") if nodo is not None else ""
    return limpiar_espacios(texto)


def es_release_github(url: str) -> bool:
    """True para URLs del estilo github.com/<dueño>/<repo>/releases/tag/<tag>."""
    partes = urlsplit(url)
    return (partes.hostname or "").lower() in ("github.com", "www.github.com") and (
        "/releases/tag/" in partes.path
    )


def _solo_alfanumerico(texto: str) -> str:
    return re.sub(r"[\W_]+", "", texto.casefold())


def titulo_de_release(titulo: str, proyecto: str) -> str:
    """Antepone el proyecto si el título no lo menciona: '0.13.1' -> 'uv 0.13.1'."""
    if _solo_alfanumerico(proyecto) in _solo_alfanumerico(titulo):
        return titulo
    return f"{proyecto} {titulo}"


def recortar(texto: str, max_caracteres: int) -> str:
    """Recorta el texto sin cortar palabras al medio y agrega `…` si hizo falta.

    El resultado nunca supera `max_caracteres` (incluido el `…`).
    """
    if max_caracteres < 1:
        raise ValueError("max_caracteres tiene que ser positivo")
    if len(texto) <= max_caracteres:
        return texto

    corte = texto[: max_caracteres - 1]
    ultimo_espacio = corte.rfind(" ")
    # Si la única "palabra" es enorme (ej. una URL), cortamos donde caiga.
    if ultimo_espacio > max_caracteres // 2:
        corte = corte[:ultimo_espacio]
    return corte.rstrip(" ,.;:-") + "…"
