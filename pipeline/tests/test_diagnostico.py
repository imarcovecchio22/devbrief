from datetime import UTC, datetime
from pathlib import Path

import httpx

from diario.config import Fuente, FuenteReddit, FuenteRss, FuenteScrape
from diario.diagnostico import Estado, probar_fuentes

FIXTURES = Path(__file__).parent / "fixtures"


def _rss(nombre: str, path: str) -> FuenteRss:
    return FuenteRss(nombre=nombre, tipo="rss", url=f"https://ejemplo.com{path}", area="x")


def test_probar_fuentes_clasifica_cada_resultado_y_respeta_el_orden() -> None:
    feed = (FIXTURES / "atom_simonwillison.xml").read_bytes()

    def responder(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/feed":
            return httpx.Response(200, content=feed)
        if request.url.path == "/basura":
            return httpx.Response(200, content=b"<html>no es un feed")
        return httpx.Response(404)

    fuentes: list[Fuente] = [
        _rss("ok", "/feed"),
        _rss("rota", "/no-existe"),
        _rss("basura", "/basura"),
        FuenteReddit(nombre="r/x", tipo="reddit", sub="x", area="x"),
        FuenteScrape(nombre="sitio sin scraper", tipo="scrape", url="https://otro.com", area="x"),
    ]
    with httpx.Client(transport=httpx.MockTransport(responder)) as cliente:
        ok = probar_fuentes(fuentes, cliente, datetime(2000, 1, 1, tzinfo=UTC))
        vacia = probar_fuentes(fuentes[:1], cliente, datetime(2100, 1, 1, tzinfo=UTC))

    assert [r.fuente.nombre for r in ok] == [f.nombre for f in fuentes]
    assert [r.estado for r in ok] == [
        Estado.OK,
        Estado.FALLA,
        Estado.FALLA,
        Estado.SIN_FETCHER,
        Estado.SIN_FETCHER,
    ]
    assert ok[0].cantidad == 3
    assert "404" in ok[1].detalle
    assert vacia[0].estado is Estado.VACIA
