from datetime import UTC, datetime

import pytest

from diario.dedupe import Referencia, agrupar, normalizar_titulo
from diario.modelos import ItemCrudo

# El guion largo que usa HN en "Show HN: X - Y"; a la vista se confunde con "-".
GUION_LARGO = chr(0x2013)


def _item(
    titulo: str,
    url: str,
    fuente: str = "Blog",
    contenido: str = "",
    fecha: datetime | None = None,
) -> ItemCrudo:
    return ItemCrudo(
        fuente=fuente,
        area="ia",
        url=url,
        titulo=titulo,
        contenido=contenido,
        fecha_publicacion=fecha,
    )


# ---------- por URL ----------


def test_misma_url_canonica_es_un_solo_grupo_con_todas_las_fuentes() -> None:
    grupos = agrupar(
        [
            _item("Post X", "https://blog.com/x/", fuente="Blog", contenido="cuerpo completo"),
            _item("Post X (comentado)", "http://www.blog.com/x?utm_source=hn", fuente="HN"),
        ]
    )

    assert len(grupos) == 1
    g = grupos[0]
    assert g.url_canonica == "https://blog.com/x"
    assert g.fuentes == {"Blog", "HN"}
    # representante: el que trae más texto
    assert g.titulo == "Post X"
    assert g.contenido == "cuerpo completo"


def test_misma_fuente_repetida_cuenta_una_vez() -> None:
    grupos = agrupar([_item("A", "https://a.com/1"), _item("A", "https://a.com/1")])
    assert len(grupos[0].apariciones) == 1


def test_fecha_del_grupo_es_la_mas_temprana() -> None:
    temprana = datetime(2026, 10, 14, tzinfo=UTC)
    grupos = agrupar(
        [
            _item("A", "https://a.com/1", fuente="F1", fecha=datetime(2026, 10, 15, tzinfo=UTC)),
            _item("A", "https://a.com/1", fuente="F2", fecha=temprana),
            _item("A", "https://a.com/1", fuente="F3", fecha=None),
        ]
    )
    assert grupos[0].fecha_publicacion == temprana


def test_url_invalida_se_descarta_sin_romper() -> None:
    grupos = agrupar([_item("Roto", "mailto:x@y.com"), _item("Bien", "https://a.com/1")])
    assert [g.titulo for g in grupos] == ["Bien"]


def test_conserva_el_orden_de_llegada() -> None:
    urls = [f"https://a.com/{n}" for n in range(5)]
    grupos = agrupar([_item(f"Nota numero {n}", u) for n, u in enumerate(urls)])
    assert [g.url_canonica for g in grupos] == urls


# ---------- por título ----------


def test_titulos_casi_iguales_en_fuentes_distintas_se_fusionan() -> None:
    grupos = agrupar(
        [
            _item(
                "Introducing dotnetup: A toolchain manager for .NET",
                "https://devblogs.microsoft.com/dotnet/introducing-dotnetup/",
                fuente=".NET Blog",
                contenido="post largo",
            ),
            _item(
                "Introducing dotnetup, a toolchain manager for .NET",
                "https://news.ycombinator.com/item?id=1",
                fuente="HN",
            ),
        ]
    )

    assert len(grupos) == 1
    assert grupos[0].fuentes == {".NET Blog", "HN"}
    # la URL que queda es la del primer grupo
    assert grupos[0].url_canonica == "https://devblogs.microsoft.com/dotnet/introducing-dotnetup"


def test_prefijo_show_hn_no_impide_fusionar() -> None:
    grupos = agrupar(
        [
            _item(
                "Proa: a Rust web framework with fast SSR", "https://proa.dev/", fuente="Lobsters"
            ),
            _item(
                f"Show HN: Proa {GUION_LARGO} A Rust web framework with fast SSR",
                "https://x.com/1",
                "HN",
            ),
        ]
    )
    assert len(grupos) == 1


@pytest.mark.parametrize(
    ("titulo_a", "titulo_b"),
    [
        # números distintos: versiones o entregas distintas
        ("Python 3.16.0 alpha 1 is now available", "Python 3.16.0 alpha 2 is now available"),
        ("What's new in GPT-5 for developers", "What's new in GPT-4 for developers"),
        # títulos cortos: demasiado ambiguos
        ("Release notes", "Release notes"),
        # parecidos pero no tanto
        ("Building agents with Claude Code", "Building games with Three.js"),
    ],
)
def test_titulos_que_no_se_fusionan(titulo_a: str, titulo_b: str) -> None:
    grupos = agrupar(
        [
            _item(titulo_a, "https://a.com/1", fuente="F1"),
            _item(titulo_b, "https://b.com/2", fuente="F2"),
        ]
    )
    assert len(grupos) == 2


def test_misma_fuente_con_titulos_parecidos_no_se_fusiona() -> None:
    grupos = agrupar(
        [
            _item("Weeknotes: the agents are coming along", "https://blog.com/a"),
            _item("Weeknotes: the agents are coming along!", "https://blog.com/b"),
        ]
    )
    assert len(grupos) == 2


def test_releases_nunca_se_fusionan_por_titulo() -> None:
    grupos = agrupar(
        [
            _item(
                "uv 0.13.1 release with many fixes",
                "https://github.com/astral-sh/uv/releases/tag/0.13.1",
                fuente="uv releases",
            ),
            _item("uv 0.13.1 release with many fixes", "https://otro.com/uv", fuente="HN"),
        ]
    )
    assert len(grupos) == 2


def test_fusiona_tres_fuentes_en_un_grupo() -> None:
    titulo = "Anthropic releases new prompt caching features"
    grupos = agrupar(
        [
            _item(titulo, "https://a.com/1", fuente="F1"),
            _item(titulo.lower(), "https://b.com/2", fuente="F2"),
            _item(titulo + "!", "https://c.com/3", fuente="F3"),
        ]
    )
    assert len(grupos) == 1
    assert len(grupos[0].fuentes) == 3


# ---------- contra items existentes ----------


def test_grupo_parecido_a_un_existente_adopta_su_url() -> None:
    existente = Referencia(
        url_canonica="https://blog.com/viejo",
        titulo="Claude Code now supports background agents",
        fuentes=frozenset({"Blog"}),
    )
    grupos = agrupar(
        [_item("Claude Code now supports background agents", "https://hn.com/9", fuente="HN")],
        existentes=[existente],
    )
    assert grupos[0].url_canonica == "https://blog.com/viejo"


def test_existente_de_la_misma_fuente_no_se_fusiona() -> None:
    existente = Referencia(
        url_canonica="https://blog.com/parte-1",
        titulo="Building a diary pipeline with Python",
        fuentes=frozenset({"Blog"}),
    )
    grupos = agrupar(
        [_item("Building a diary pipeline with Python", "https://blog.com/parte-2")],
        existentes=[existente],
    )
    assert grupos[0].url_canonica == "https://blog.com/parte-2"


# ---------- normalizar_titulo ----------


@pytest.mark.parametrize(
    ("entrada", "esperada"),
    [
        (f"Show HN: Proa {GUION_LARGO} Rust framework", "proa rust framework"),
        ("Ask HN - What do you use?", "what do you use"),
        ("Introducing dotnetup: A toolchain for .NET", "introducing dotnetup a toolchain for net"),
        ("Ñandú_y_café", "ñandú y café"),
    ],
)
def test_normalizar_titulo(entrada: str, esperada: str) -> None:
    assert normalizar_titulo(entrada) == esperada
