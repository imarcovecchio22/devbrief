"""Tests de integración contra el branch de test de Neon (ver conftest.py)."""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from diario.config import FuenteRss
from diario.dedupe import Grupo, agrupar
from diario.modelos import ItemCrudo
from diario.pipeline import completar_contenido, ingestar
from diario.repositorio import Repositorio

FIXTURES = Path(__file__).parent / "fixtures"
HTML = {"content-type": "text/html; charset=utf-8"}


def _item(
    url: str, fuente: str = "Blog", senal: int | None = None, contenido: str = ""
) -> ItemCrudo:
    return ItemCrudo(
        fuente=fuente,
        area="ia",
        url=url,
        titulo=f"Nota en {url}",
        contenido=contenido,
        fecha_publicacion=datetime(2026, 10, 15, tzinfo=UTC),
        senal=senal,
    )


def _contar(repo: Repositorio, tabla: str) -> int:
    fila = repo._db.execute(f"SELECT count(*) FROM {tabla}").fetchone()
    assert fila is not None
    return int(fila[0])


def _uno(repo: Repositorio, sql: str, *params: Any) -> Any:
    fila = repo._db.execute(sql, params).fetchone()
    assert fila is not None
    return fila[0]


def test_guardar_es_idempotente(repo: Repositorio) -> None:
    grupos = agrupar([_item("https://a.com/1"), _item("https://a.com/2")])

    primera = repo.guardar_grupos(grupos, max_contenido=100)
    segunda = repo.guardar_grupos(grupos, max_contenido=100)

    assert (primera.items_nuevos, primera.apariciones_nuevas) == (2, 2)
    assert (segunda.items_nuevos, segunda.apariciones_nuevas) == (0, 0)
    assert _contar(repo, "items") == 2
    assert _contar(repo, "item_fuentes") == 2


def test_un_grupo_con_varias_fuentes_guarda_cada_aparicion(repo: Repositorio) -> None:
    grupos = agrupar(
        [_item("https://a.com/1", "Blog"), _item("http://www.a.com/1/?utm_source=x", "HN", 200)]
    )
    repo.guardar_grupos(grupos, max_contenido=100)

    assert _contar(repo, "items") == 1
    filas = repo._db.execute(
        "SELECT fuente, url_original, senal FROM item_fuentes ORDER BY fuente"
    ).fetchall()
    assert filas == [
        ("Blog", "https://a.com/1", None),
        ("HN", "http://www.a.com/1/?utm_source=x", 200),
    ]


def test_nueva_fuente_para_un_item_existente_suma_aparicion(repo: Repositorio) -> None:
    repo.guardar_grupos(agrupar([_item("https://a.com/1", "Blog")]), max_contenido=100)
    resultado = repo.guardar_grupos(agrupar([_item("https://a.com/1", "HN")]), max_contenido=100)

    assert (resultado.items_nuevos, resultado.apariciones_nuevas) == (0, 1)
    assert _contar(repo, "items") == 1
    assert _contar(repo, "item_fuentes") == 2


def test_la_senal_solo_sube(repo: Repositorio) -> None:
    for puntos in (150, 300, 200):
        repo.guardar_grupos(agrupar([_item("https://a.com/1", "HN", puntos)]), max_contenido=100)
    assert _uno(repo, "SELECT senal FROM item_fuentes") == 300


def test_guarda_el_contenido_recortado(repo: Repositorio) -> None:
    repo.guardar_grupos(
        agrupar([_item("https://a.com/1", contenido="palabra " * 100)]), max_contenido=50
    )
    contenido = _uno(repo, "SELECT contenido_resumido FROM items")
    assert len(contenido) <= 50
    assert contenido.endswith("…")


def test_item_nuevo_queda_sin_puntuar(repo: Repositorio) -> None:
    repo.guardar_grupos(agrupar([_item("https://a.com/1")]), max_contenido=100)
    fila = repo._db.execute("SELECT puntaje, intentos_puntaje, diario_id FROM items").fetchone()
    assert fila == (None, 0, None)


def test_referencias_recientes_trae_todas_las_fuentes(repo: Repositorio) -> None:
    grupo = Grupo("https://a.com/1")
    grupo.agregar([_item("https://a.com/1", "Blog"), _item("https://a.com/1", "HN")])
    repo.guardar_grupos([grupo], max_contenido=100)

    [ref] = repo.referencias_recientes(dias=7)
    assert ref.url_canonica == "https://a.com/1"
    assert ref.fuentes == {"Blog", "HN"}


def test_corrida_registra_inicio_fin_y_errores(repo: Repositorio) -> None:
    corrida = repo.iniciar_corrida()
    repo.cerrar_corrida(
        corrida, items_nuevos=5, tokens_entrada=1000, errores=[{"fuente": "X", "error": "404"}]
    )
    fila = repo._db.execute(
        "SELECT fin IS NOT NULL, items_nuevos, tokens_entrada, errores FROM corridas"
    ).fetchone()
    assert fila == (True, 5, 1000, [{"fuente": "X", "error": "404"}])


# ---------- ingesta de punta a punta ----------


def test_ingestar_de_punta_a_punta_tolera_fuentes_caidas(repo: Repositorio) -> None:
    feed = (FIXTURES / "atom_simonwillison.xml").read_bytes()

    def responder(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/feed":
            return httpx.Response(200, content=feed)
        return httpx.Response(503)

    fuentes = [
        FuenteRss(nombre="Simon", tipo="rss", url="https://ejemplo.com/feed", area="ia"),
        FuenteRss(nombre="Caída", tipo="rss", url="https://ejemplo.com/caida", area="ia"),
    ]
    parametros: dict[str, Any] = {
        "desde": datetime(2000, 1, 1, tzinfo=UTC),
        "dias_dedupe": 7,
        "max_contenido": 2000,
    }

    with httpx.Client(transport=httpx.MockTransport(responder)) as cliente:
        primera = ingestar(repo, fuentes, cliente, **parametros)
        segunda = ingestar(repo, fuentes, cliente, **parametros)

    assert primera.items_nuevos == 3
    assert [e["fuente"] for e in primera.errores] == ["Caída"]
    assert "503" in primera.errores[0]["error"]
    # correr dos veces no duplica nada
    assert segunda.items_nuevos == 0
    assert segunda.apariciones_nuevas == 0
    assert _contar(repo, "items") == 3


# ---------- completar contenido ----------


def test_completar_contenido_solo_toca_items_sin_texto_y_sin_puntaje(repo: Repositorio) -> None:
    repo.guardar_grupos(
        agrupar(
            [
                _item("https://a.com/vacio", "HN"),
                _item("https://a.com/bloqueado", "HN"),
                _item("https://a.com/con-texto", "Blog", contenido="ya tengo texto"),
                _item("https://a.com/puntuado", "HN"),
            ]
        ),
        max_contenido=100,
    )
    repo._db.execute("UPDATE items SET puntaje = 5 WHERE url_canonica = 'https://a.com/puntuado'")
    pedidas: list[str] = []

    def responder(request: httpx.Request) -> httpx.Response:
        pedidas.append(request.url.path)
        if request.url.path == "/bloqueado":
            return httpx.Response(403)
        return httpx.Response(200, text="<article>" + "texto " * 100 + "</article>", headers=HTML)

    with httpx.Client(transport=httpx.MockTransport(responder)) as cliente:
        resumen = completar_contenido(repo, cliente, max_contenido=50)

    assert sorted(pedidas) == ["/bloqueado", "/vacio"]
    assert (resumen.pendientes, resumen.completados) == (2, 1)
    contenidos = dict(
        repo._db.execute("SELECT url_canonica, contenido_resumido FROM items").fetchall()
    )
    assert contenidos["https://a.com/vacio"].startswith("texto texto")
    assert len(contenidos["https://a.com/vacio"]) <= 50
    assert contenidos["https://a.com/bloqueado"] == ""
    assert contenidos["https://a.com/con-texto"] == "ya tengo texto"
