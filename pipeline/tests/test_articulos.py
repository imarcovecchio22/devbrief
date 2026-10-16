import httpx
import pytest

from diario.fuentes.articulos import descargar_texto, descargar_textos, extraer_texto_principal

HTML = {"content-type": "text/html; charset=utf-8"}


@pytest.mark.parametrize(
    ("html", "esperado"),
    [
        (
            "<body><nav>Menú</nav><article><h1>Título</h1><p>Cuerpo</p></article>"
            "<footer>Pie</footer></body>",
            "Título Cuerpo",
        ),
        ("<body><header>Logo</header><main><p>Solo main</p></main></body>", "Solo main"),
        ('<body><div role="main">Rol main</div><aside>Lateral</aside></body>', "Rol main"),
        (
            "<body><nav>Menú</nav><div><p>Sin marcas</p></div><footer>Pie</footer></body>",
            "Sin marcas",
        ),
        ("<body><article><script>x()</script><p>Limpio</p></article></body>", "Limpio"),
        ("", ""),
    ],
)
def test_extraer_texto_principal(html: str, esperado: str) -> None:
    assert extraer_texto_principal(html) == esperado


def _cliente(responder: httpx.MockTransport) -> httpx.Client:
    return httpx.Client(transport=responder)


def test_descargar_texto_de_una_pagina_html() -> None:
    def responder(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<article>Hola</article>", headers=HTML)

    with _cliente(httpx.MockTransport(responder)) as cliente:
        assert descargar_texto(cliente, "https://blog.com/post") == "Hola"


@pytest.mark.parametrize(
    "respuesta",
    [
        httpx.Response(403, text="Forbidden", headers=HTML),
        httpx.Response(200, content=b"%PDF-1.7", headers={"content-type": "application/pdf"}),
        httpx.Response(200, text="<article>x</article>" * 200_000, headers=HTML),
    ],
    ids=["bloqueado", "pdf", "enorme"],
)
def test_descargar_texto_devuelve_vacio_si_no_sirve(respuesta: httpx.Response) -> None:
    with _cliente(httpx.MockTransport(lambda _: respuesta)) as cliente:
        assert descargar_texto(cliente, "https://blog.com/post") == ""


def test_descargar_texto_tolera_errores_de_red() -> None:
    def responder(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("tardó demasiado")

    with _cliente(httpx.MockTransport(responder)) as cliente:
        assert descargar_texto(cliente, "https://blog.com/post") == ""


def test_no_baja_discusiones_de_hn() -> None:
    pedidas: list[str] = []

    def responder(request: httpx.Request) -> httpx.Response:
        pedidas.append(str(request.url))
        return httpx.Response(200, text="<article>x</article>", headers=HTML)

    with _cliente(httpx.MockTransport(responder)) as cliente:
        assert descargar_texto(cliente, "https://news.ycombinator.com/item?id=1") == ""
    assert pedidas == []


def test_descargar_textos_respeta_el_orden() -> None:
    def responder(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=f"<main>{request.url.path}</main>", headers=HTML)

    urls = [f"https://blog.com/{n}" for n in range(10)]
    with _cliente(httpx.MockTransport(responder)) as cliente:
        assert descargar_textos(cliente, urls) == [f"/{n}" for n in range(10)]
