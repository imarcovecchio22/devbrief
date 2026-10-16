import pytest

from diario.normalizacion import (
    canonicalizar_url,
    es_release_github,
    html_a_texto,
    limpiar_espacios,
    recortar,
    titulo_de_release,
)

# ---------- canonicalizar_url ----------


@pytest.mark.parametrize(
    ("entrada", "esperada"),
    [
        # http -> https, host en minúscula, sin www
        ("http://WWW.Ejemplo.com/Post", "https://ejemplo.com/Post"),
        # el path conserva mayúsculas: en muchos servidores importan
        ("https://ejemplo.com/Post/", "https://ejemplo.com/Post"),
        # la raíz queda con su /
        ("https://ejemplo.com", "https://ejemplo.com/"),
        ("https://ejemplo.com/", "https://ejemplo.com/"),
        # fragmento afuera
        ("https://ejemplo.com/a#comentarios", "https://ejemplo.com/a"),
        # tracking afuera, el resto ordenado
        (
            "https://ejemplo.com/a?utm_source=x&b=2&UTM_Medium=y&a=1&fbclid=z",
            "https://ejemplo.com/a?a=1&b=2",
        ),
        # puerto default afuera, no default se queda
        ("https://ejemplo.com:443/a", "https://ejemplo.com/a"),
        ("http://ejemplo.com:80/a", "https://ejemplo.com/a"),
        ("https://ejemplo.com:8080/a", "https://ejemplo.com:8080/a"),
        # espacios alrededor
        ("  https://ejemplo.com/a  ", "https://ejemplo.com/a"),
        # parámetro vacío que no es tracking se conserva
        ("https://ejemplo.com/a?flag=", "https://ejemplo.com/a?flag="),
    ],
)
def test_canonicalizar_url(entrada: str, esperada: str) -> None:
    assert canonicalizar_url(entrada) == esperada


def test_canonicalizar_es_idempotente() -> None:
    url = "http://www.Ejemplo.com/a/?utm_source=x&z=1&a=2#top"
    una_vez = canonicalizar_url(url)
    assert canonicalizar_url(una_vez) == una_vez


def test_variantes_de_la_misma_url_coinciden() -> None:
    variantes = [
        "https://simonwillison.net/2026/Oct/15/algo/",
        "http://simonwillison.net/2026/Oct/15/algo",
        "https://www.simonwillison.net/2026/Oct/15/algo/?utm_source=hn#comments",
    ]
    assert len({canonicalizar_url(v) for v in variantes}) == 1


@pytest.mark.parametrize(
    "invalida", ["ftp://ejemplo.com/a", "mailto:a@b.com", "no es una url", "https://"]
)
def test_canonicalizar_rechaza_urls_invalidas(invalida: str) -> None:
    with pytest.raises(ValueError):
        canonicalizar_url(invalida)


# ---------- html_a_texto ----------


def test_html_a_texto_decodifica_entidades_y_colapsa_espacios() -> None:
    html = "<p>Hola &amp; <b>chau</b></p>\n\n<p>  otro\tpárrafo&nbsp;más </p>"
    assert html_a_texto(html) == "Hola & chau otro párrafo más"


def test_html_a_texto_descarta_scripts_y_estilos() -> None:
    html = "<style>p{color:red}</style><p>visible</p><script>alert(1)</script>"
    assert html_a_texto(html) == "visible"


def test_html_a_texto_con_texto_plano() -> None:
    assert html_a_texto("sin etiquetas") == "sin etiquetas"


def test_html_a_texto_vacio() -> None:
    assert html_a_texto("   ") == ""


def test_limpiar_espacios() -> None:
    assert limpiar_espacios("  a \n\t b  ") == "a b"


# ---------- recortar ----------


def test_recortar_texto_corto_no_cambia() -> None:
    assert recortar("hola mundo", 50) == "hola mundo"


def test_recortar_no_corta_palabras_al_medio() -> None:
    resultado = recortar("uno dos tres cuatro cinco", 12)
    assert resultado == "uno dos…"
    assert len(resultado) <= 12


def test_recortar_saca_puntuacion_colgada() -> None:
    assert recortar("uno, dos, tres, cuatro", 10) == "uno, dos…"


def test_recortar_palabra_gigante_corta_igual() -> None:
    url = "https://ejemplo.com/" + "a" * 100
    resultado = recortar(url, 30)
    assert len(resultado) == 30
    assert resultado.endswith("…")


@pytest.mark.parametrize("maximo", [1, 5, 17, 100])
def test_recortar_nunca_supera_el_maximo(maximo: int) -> None:
    assert len(recortar("palabra " * 50, maximo)) <= maximo


def test_recortar_maximo_invalido() -> None:
    with pytest.raises(ValueError):
        recortar("x", 0)


# ---------- releases de GitHub ----------


@pytest.mark.parametrize(
    ("url", "esperado"),
    [
        ("https://github.com/astral-sh/uv/releases/tag/0.13.1", True),
        ("https://github.com/n8n-io/n8n/releases/tag/n8n%402.44.3", True),
        ("https://github.com/astral-sh/uv", False),
        ("https://github.com/astral-sh/uv/releases", False),
        ("https://blog.com/releases/tag/x", False),
    ],
)
def test_es_release_github(url: str, esperado: bool) -> None:
    assert es_release_github(url) is esperado


@pytest.mark.parametrize(
    ("titulo", "proyecto", "esperado"),
    [
        ("0.13.1", "uv", "uv 0.13.1"),
        ("r186", "Three.js", "Three.js r186"),
        ("v2.1.301", "Claude Code", "Claude Code v2.1.301"),
        # ya lo menciona (ignorando mayúsculas y puntuación): no se toca
        ("n8n@2.44.3", "n8n", "n8n@2.44.3"),
        ("OrcaSlicer V2.5.0 Alpha release", "OrcaSlicer", "OrcaSlicer V2.5.0 Alpha release"),
        ("claude-code 2.0", "Claude Code", "claude-code 2.0"),
    ],
)
def test_titulo_de_release(titulo: str, proyecto: str, esperado: str) -> None:
    assert titulo_de_release(titulo, proyecto) == esperado
