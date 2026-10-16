from pathlib import Path

import pytest

from diario.config import (
    ErrorConfig,
    FuenteHn,
    FuenteRss,
    cargar_fuentes,
    parsear_fuentes,
)
from diario.settings import RAIZ_REPO


def test_archivo_real_tiene_las_seis_activas_del_mvp() -> None:
    activas = cargar_fuentes(RAIZ_REPO / "config" / "fuentes.yaml")

    assert {f.nombre for f in activas} == {
        "Simon Willison",
        "Claude Code releases",
        "Anthropic News",
        ".NET Blog",
        "Real Python",
        "Hacker News portada",
    }


def test_archivo_real_parsea_todas_las_fuentes() -> None:
    todas = cargar_fuentes(RAIZ_REPO / "config" / "fuentes.yaml", solo_activas=False)
    assert len(todas) > 6


def test_el_tipo_elige_la_clase_correcta() -> None:
    fuentes = parsear_fuentes(
        """
        - {nombre: Blog, tipo: rss, url: "https://ejemplo.com/feed", area: ia, activa: true}
        - {nombre: HN, tipo: hn, min_puntaje: 150, area: general}
        """
    )
    assert isinstance(fuentes[0], FuenteRss)
    assert isinstance(fuentes[1], FuenteHn)
    assert fuentes[1].min_puntaje == 150
    assert fuentes[1].activa is False  # default


@pytest.mark.parametrize(
    "yaml_invalido",
    [
        "- {nombre: X, tipo: rss, area: ia}",  # falta url
        "- {nombre: X, tipo: telegrama, area: ia}",  # tipo desconocido
        "- {nombre: X, tipo: hn, area: ia, minpuntaje: 3}",  # campo mal escrito
        "- {nombre: X, tipo: rss, url: no-es-url, area: ia}",
        "- [esto, no, es, un, mapa",  # YAML roto
    ],
)
def test_yaml_invalido_da_error_claro(yaml_invalido: str) -> None:
    with pytest.raises(ErrorConfig):
        parsear_fuentes(yaml_invalido)


def test_nombres_repetidos_son_error() -> None:
    with pytest.raises(ErrorConfig, match="repetidos"):
        parsear_fuentes(
            """
            - {nombre: A, tipo: hn, area: x}
            - {nombre: A, tipo: hn, area: y}
            """
        )


def test_archivo_inexistente(tmp_path: Path) -> None:
    with pytest.raises(ErrorConfig, match="No se pudo leer"):
        cargar_fuentes(tmp_path / "no-existe.yaml")
