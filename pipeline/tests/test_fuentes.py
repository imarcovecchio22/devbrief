import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from diario.config import FuenteHn, FuenteReddit, FuenteRss
from diario.fuentes import ErrorFuente, FuenteNoSoportada, hn, rss, traer_items

FIXTURES = Path(__file__).parent / "fixtures"
MUY_ATRAS = datetime(2000, 1, 1, tzinfo=UTC)


def _leer(nombre: str) -> bytes:
    return (FIXTURES / nombre).read_bytes()


def _fuente_rss(url: str = "https://ejemplo.com/feed", nombre: str = "Prueba") -> FuenteRss:
    return FuenteRss(nombre=nombre, tipo="rss", url=url, area="ia", activa=True)


def _fuente_hn(min_puntaje: int = 150) -> FuenteHn:
    return FuenteHn(nombre="HN", tipo="hn", min_puntaje=min_puntaje, area="general", activa=True)


def _cliente(manejador: httpx.MockTransport) -> httpx.Client:
    return httpx.Client(transport=manejador)


# ---------- RSS / Atom ----------


def test_atom_simon_willison() -> None:
    items = rss.parsear(_leer("atom_simonwillison.xml"), _fuente_rss(), MUY_ATRAS)

    assert len(items) == 3
    primero = items[0]
    assert primero.titulo == "Chirp Pong"
    assert primero.url == "https://simonwillison.net/2026/Oct/15/chirp-pong/"
    assert primero.fecha_publicacion == datetime(2026, 10, 15, 19, 47, 52, tzinfo=UTC)
    assert primero.fuente == "Prueba"
    assert primero.area == "ia"
    assert primero.contenido
    assert "<" not in primero.contenido  # sin HTML


def test_atom_github_releases_usa_updated_como_fecha() -> None:
    fuente = _fuente_rss(nombre="Claude Code releases")
    items = rss.parsear(_leer("atom_github_releases.xml"), fuente, MUY_ATRAS)

    assert len(items) == 3
    assert items[0].fecha_publicacion == datetime(2026, 10, 15, 19, 22, 6, tzinfo=UTC)


def test_atom_github_releases_agrega_el_proyecto_al_titulo() -> None:
    fuente = _fuente_rss(nombre="Claude Code releases")
    items = rss.parsear(_leer("atom_github_releases.xml"), fuente, MUY_ATRAS)

    # el feed solo dice "v2.1.301"
    assert items[0].titulo == "Claude Code v2.1.301"


def test_rss20_prefiere_el_contenido_completo_al_extracto() -> None:
    items = rss.parsear(_leer("rss20_dotnet.xml"), _fuente_rss(), MUY_ATRAS)

    assert items[0].titulo == "Introducing dotnetup: A toolchain manager for .NET"
    # el <description> tiene ~350 caracteres; el <content:encoded>, el post entero
    assert len(items[0].contenido) > 2000


def test_rss_filtra_por_fecha() -> None:
    contenido = _leer("atom_simonwillison.xml")
    todos = rss.parsear(contenido, _fuente_rss(), None)
    fechas = sorted(i.fecha_publicacion for i in todos if i.fecha_publicacion)

    recientes = rss.parsear(contenido, _fuente_rss(), desde=fechas[-1])
    assert len(recientes) == 1  # solo el más nuevo (el límite es inclusivo)

    futuro = datetime(2100, 1, 1, tzinfo=UTC)
    assert rss.parsear(contenido, _fuente_rss(), futuro) == []


def test_rss_saltea_entradas_sin_link_o_titulo_y_conserva_sin_fecha() -> None:
    xml = b"""<?xml version="1.0"?>
    <rss version="2.0"><channel><title>t</title>
      <item><title>Sin link</title></item>
      <item><link>https://ejemplo.com/sin-titulo</link></item>
      <item><title>Sin fecha</title><link>https://ejemplo.com/ok</link></item>
    </channel></rss>"""
    items = rss.parsear(xml, _fuente_rss(), MUY_ATRAS)

    assert [i.titulo for i in items] == ["Sin fecha"]
    assert items[0].fecha_publicacion is None


def test_rss_invalido_lanza_error_fuente() -> None:
    with pytest.raises(ErrorFuente):
        rss.parsear(b"<html><body>esto no es un feed", _fuente_rss(), None)


def test_rss_traer_hace_el_get_y_propaga_errores_http() -> None:
    def responder(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/feed":
            return httpx.Response(200, content=_leer("atom_simonwillison.xml"))
        return httpx.Response(500)

    with _cliente(httpx.MockTransport(responder)) as cliente:
        assert len(rss.traer(_fuente_rss(), cliente, MUY_ATRAS)) == 3
        with pytest.raises(httpx.HTTPStatusError):
            rss.traer(_fuente_rss("https://ejemplo.com/roto"), cliente, MUY_ATRAS)


# ---------- Hacker News ----------


def test_hn_parsea_la_respuesta_de_algolia() -> None:
    items = hn.parsear(_leer("hn_algolia.json"), _fuente_hn(), MUY_ATRAS)

    assert len(items) == 4
    assert items[0].titulo == "I Love Software Rendering"
    assert items[0].url == "https://www.jamesfmackenzie.com/2026/10/13/i-love-software-rendering/"
    assert items[0].senal == 164
    assert items[0].fecha_publicacion is not None
    assert items[0].fecha_publicacion.tzinfo is UTC


def test_hn_filtra_por_puntaje_minimo() -> None:
    items = hn.parsear(_leer("hn_algolia.json"), _fuente_hn(min_puntaje=200), MUY_ATRAS)
    assert {i.senal for i in items} == {219, 474}


def test_hn_sin_url_usa_la_discusion_y_el_texto() -> None:
    respuesta = {
        "hits": [
            {
                "objectID": "123",
                "title": "Ask HN: ¿Qué usan para X?",
                "url": None,
                "points": 300,
                "created_at_i": 1_800_000_000,
                "story_text": "<p>Pregunta &amp; contexto</p>",
            }
        ]
    }
    items = hn.parsear(json.dumps(respuesta).encode(), _fuente_hn(), MUY_ATRAS)

    assert items[0].url == "https://news.ycombinator.com/item?id=123"
    assert items[0].contenido == "Pregunta & contexto"


def test_hn_respuesta_inesperada_lanza_error_fuente() -> None:
    with pytest.raises(ErrorFuente):
        hn.parsear(b'{"error": "rate limited"}', _fuente_hn(), None)


def test_hn_traer_manda_los_filtros_a_la_api() -> None:
    pedidos: list[httpx.Request] = []

    def responder(request: httpx.Request) -> httpx.Response:
        pedidos.append(request)
        return httpx.Response(200, content=_leer("hn_algolia.json"))

    desde = datetime(2026, 10, 15, tzinfo=UTC)
    with _cliente(httpx.MockTransport(responder)) as cliente:
        hn.traer(_fuente_hn(min_puntaje=150), cliente, MUY_ATRAS)
        hn.traer(_fuente_hn(min_puntaje=150), cliente, desde)

    params = pedidos[1].url.params
    assert params["tags"] == "story"
    assert params["numericFilters"] == f"points>=150,created_at_i>{int(desde.timestamp())}"


# ---------- despacho ----------


def test_traer_items_elige_el_fetcher_por_tipo() -> None:
    def responder(request: httpx.Request) -> httpx.Response:
        if request.url.host == "hn.algolia.com":
            return httpx.Response(200, content=_leer("hn_algolia.json"))
        return httpx.Response(200, content=_leer("rss20_dotnet.xml"))

    with _cliente(httpx.MockTransport(responder)) as cliente:
        assert len(traer_items(_fuente_hn(), cliente, MUY_ATRAS)) == 4
        assert len(traer_items(_fuente_rss(), cliente, MUY_ATRAS)) == 3


def test_tipo_sin_fetcher_lanza_fuente_no_soportada() -> None:
    reddit = FuenteReddit(nombre="r/x", tipo="reddit", sub="x", area="ia")
    with httpx.Client() as cliente, pytest.raises(FuenteNoSoportada):
        traer_items(reddit, cliente, MUY_ATRAS)
