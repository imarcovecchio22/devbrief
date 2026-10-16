"""Excepciones y utilidades compartidas por los fetchers."""

import httpx

USER_AGENT = "diario-tecnico/0.1 (lector personal de novedades)"


class ErrorFuente(Exception):
    """La fuente respondió, pero con algo que no se puede interpretar."""


class FuenteNoSoportada(ErrorFuente):
    """El `tipo` de la fuente todavía no tiene fetcher."""


def crear_cliente() -> httpx.Client:
    return httpx.Client(
        timeout=20.0,
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT},
    )
