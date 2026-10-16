import json
from typing import Any

import pytest

from diario.config import cargar_fuentes
from diario.llm.puntaje import MAX_MOTIVO, parsear_puntaje
from diario.llm.respuesta import ErrorRespuestaLLM, extraer_objeto_json
from diario.secciones import SECCIONES, resolver_seccion
from diario.settings import RAIZ_REPO

# ---------- extraer_objeto_json ----------


@pytest.mark.parametrize(
    "texto",
    [
        '{"a": 1}',
        '  {"a": 1}\n',
        '```json\n{"a": 1}\n```',
        '```\n{"a": 1}\n```',
        'Acá va el resultado:\n```JSON\n{"a": 1}\n```\nEspero que sirva.',
        'Claro: {"a": 1} listo.',
    ],
)
def test_extrae_json_en_distintos_envoltorios(texto: str) -> None:
    assert extraer_objeto_json(texto) == {"a": 1}


def test_extrae_json_con_llaves_dentro_de_strings() -> None:
    assert extraer_objeto_json('{"motivo": "usa {llaves}"}') == {"motivo": "usa {llaves}"}


@pytest.mark.parametrize(
    "texto",
    ["", "No puedo ayudar con eso.", '{"a": 1', "[1, 2, 3]", '{"a": 1,}', "```json\n```"],
)
def test_texto_sin_objeto_json_es_error(texto: str) -> None:
    with pytest.raises(ErrorRespuestaLLM):
        extraer_objeto_json(texto)


# ---------- secciones ----------


def test_todas_las_areas_de_fuentes_yaml_son_secciones() -> None:
    fuentes = cargar_fuentes(RAIZ_REPO / "config" / "fuentes.yaml", solo_activas=False)
    assert {f.area for f in fuentes} <= set(SECCIONES)


@pytest.mark.parametrize(
    ("valor", "esperada"),
    [
        ("ia", "ia"),
        ("IA aplicada", "ia"),
        (".NET y C#", "dotnet"),
        ("DotNet", "dotnet"),
        ("Impresión 3D", "impresion3d"),
        ("impresion 3d", "impresion3d"),
        ("  Python ", "python"),
    ],
)
def test_resolver_seccion_acepta_clave_o_nombre(valor: str, esperada: str) -> None:
    assert resolver_seccion(valor) == esperada


def test_resolver_seccion_desconocida_usa_respaldo() -> None:
    assert resolver_seccion("Cocina", respaldo="python") == "python"
    assert resolver_seccion(None, respaldo="python") == "python"
    # respaldo inválido -> general
    assert resolver_seccion("Cocina", respaldo="tampoco-existe") == "general"


# ---------- parsear_puntaje ----------


def _puntaje(**campos: Any) -> str:
    base = {"puntaje": 8, "seccion": "ia", "motivo": "Release de Claude Code con hooks nuevos."}
    return json.dumps(base | campos)


def test_puntaje_valido() -> None:
    p = parsear_puntaje(_puntaje(), area_respaldo="general")
    assert (p.puntaje, p.seccion) == (8, "ia")
    assert p.motivo == "Release de Claude Code con hooks nuevos."


@pytest.mark.parametrize(("valor", "esperado"), [("8", 8), (8.0, 8), (0, 0), (10, 10)])
def test_puntaje_coerciones_aceptadas(valor: Any, esperado: int) -> None:
    assert parsear_puntaje(_puntaje(puntaje=valor), area_respaldo="ia").puntaje == esperado


@pytest.mark.parametrize("valor", [-1, 11, 7.5, "alto", None])
def test_puntaje_fuera_de_rango_o_no_entero_es_error(valor: Any) -> None:
    with pytest.raises(ErrorRespuestaLLM):
        parsear_puntaje(_puntaje(puntaje=valor), area_respaldo="ia")


def test_puntaje_sin_motivo_es_error() -> None:
    with pytest.raises(ErrorRespuestaLLM):
        parsear_puntaje(_puntaje(motivo=""), area_respaldo="ia")


def test_puntaje_seccion_desconocida_o_ausente_usa_el_area() -> None:
    assert parsear_puntaje(_puntaje(seccion="Cocina"), area_respaldo="python").seccion == "python"
    sin_seccion = json.dumps({"puntaje": 5, "motivo": "x"})
    assert parsear_puntaje(sin_seccion, area_respaldo="dotnet").seccion == "dotnet"


def test_puntaje_motivo_largo_se_recorta() -> None:
    p = parsear_puntaje(_puntaje(motivo="x" * 2000), area_respaldo="ia")
    assert len(p.motivo) == MAX_MOTIVO


def test_puntaje_en_bloque_de_codigo() -> None:
    p = parsear_puntaje(f"```json\n{_puntaje(puntaje=9)}\n```", area_respaldo="ia")
    assert p.puntaje == 9
