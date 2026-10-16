from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from diario.config import FuenteScrape
from diario.fuentes import ErrorFuente, anthropic_news, traer_items
from diario.fuentes.articulos import extraer_texto_principal

FIXTURES = Path(__file__).parent / "fixtures"
BASE = "https://www.anthropic.com/news"
HTML = {"content-type": "text/html; charset=utf-8"}


def _leer(nombre: str) -> str:
    return (FIXTURES / nombre).read_text(encoding="utf-8")


def _fuente() -> FuenteScrape:
    return FuenteScrape(nombre="Anthropic News", tipo="scrape", url=BASE, area="ia", activa=True)


def test_listado_extrae_todas_las_notas_sin_repetir() -> None:
    tarjetas = anthropic_news.parsear_listado(_leer("anthropic_news_listado.html"), BASE)

    urls = [t.url for t in tarjetas]
    assert len(urls) == len(set(urls)) == 10
    assert all(u.startswith("https://www.anthropic.com/news/") for u in urls)


def test_listado_tarjeta_destacada_tiene_resumen() -> None:
    tarjetas = anthropic_news.parsear_listado(_leer("anthropic_news_listado.html"), BASE)
    destacada = tarjetas[0]

    assert destacada.url == "https://www.anthropic.com/news/cyber-verification-program"
    assert destacada.titulo == "Expanding the Cyber Verification Program"
    assert destacada.fecha == datetime(2026, 10, 6, tzinfo=UTC)
    assert "Cyber Verification Program" in destacada.resumen


def test_listado_tarjeta_comun() -> None:
    tarjetas = anthropic_news.parsear_listado(_leer("anthropic_news_listado.html"), BASE)
    por_url = {t.url.rsplit("/", 1)[-1]: t for t in tarjetas}

    nota = por_url["an-update-on-independent-evaluators"]
    assert nota.titulo == "An update on independent evaluators"
    assert nota.fecha == datetime(2026, 10, 15, tzinfo=UTC)
    # el título original tiene un espacio adelante
    assert por_url["claude-discovers-novel-enzyme-system"].titulo.startswith("Claude")


def test_listado_sin_notas_es_error() -> None:
    with pytest.raises(ErrorFuente, match="cambió el HTML"):
        anthropic_news.parsear_listado("<html><body><p>Rediseño!</p></body></html>", BASE)


def test_listado_prefiere_el_atributo_datetime() -> None:
    html = '<a href="/news/x"><h3>X</h3><time datetime="2026-10-01T15:00:00Z">ayer</time></a>'
    [tarjeta] = anthropic_news.parsear_listado(html, BASE)
    assert tarjeta.fecha == datetime(2026, 10, 1, 15, tzinfo=UTC)


def test_articulo_extrae_solo_el_cuerpo() -> None:
    texto = extraer_texto_principal(_leer("anthropic_news_articulo.html"))

    assert "An update on independent evaluators" in texto
    assert "METR" in texto
    assert "Menú del sitio" not in texto


@pytest.mark.parametrize(
    ("texto", "esperada"),
    [
        ("Oct 6, 2026", datetime(2026, 10, 6, tzinfo=UTC)),
        ("Sept. 23, 2026", datetime(2026, 9, 23, tzinfo=UTC)),
        ("September 23, 2026", datetime(2026, 9, 23, tzinfo=UTC)),
        ("  Published Jan 1,2027 ", datetime(2027, 1, 1, tzinfo=UTC)),
        ("Feb 31, 2026", None),
        ("Foo 3, 2026", None),
        ("hace 2 días", None),
    ],
)
def test_parsear_fecha_en_ingles(texto: str, esperada: datetime | None) -> None:
    assert anthropic_news.parsear_fecha_en_ingles(texto) == esperada


def test_traer_filtra_por_ventana_y_baja_cada_nota() -> None:
    pedidas: list[str] = []

    def responder(request: httpx.Request) -> httpx.Response:
        pedidas.append(request.url.path)
        if request.url.path == "/news":
            return httpx.Response(200, text=_leer("anthropic_news_listado.html"), headers=HTML)
        if request.url.path == "/news/an-update-on-independent-evaluators":
            return httpx.Response(200, text=_leer("anthropic_news_articulo.html"), headers=HTML)
        return httpx.Response(404)

    desde = datetime(2026, 10, 14, tzinfo=UTC)
    with httpx.Client(transport=httpx.MockTransport(responder)) as cliente:
        items = traer_items(_fuente(), cliente, desde)

    # 1 nota del 15/10 y 2 del 14/10; las más viejas no se piden
    assert len(items) == 3
    assert len(pedidas) == 1 + 3
    por_titulo = {i.titulo: i for i in items}
    assert "METR" in por_titulo["An update on independent evaluators"].contenido
    # una nota que da 404 no rompe la fuente: queda con el resumen (vacío acá)
    assert por_titulo["Preparing for the 2026 US midterms"].contenido == ""
