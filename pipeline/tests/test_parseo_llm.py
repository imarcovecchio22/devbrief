import json
import logging
from typing import Any

import pytest

from diario.config import cargar_fuentes
from diario.llm.puntaje import MAX_MOTIVO, parsear_puntaje
from diario.llm.redaccion import MAX_NOTAS, Candidato, parsear_diario
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


# ---------- parsear_diario ----------


def _candidatos(n: int = 3, seccion: str = "ia") -> dict[int, Candidato]:
    return {
        i: Candidato(
            item_id=i,
            url=f"https://ejemplo.com/{i}",
            fuentes=("Blog", "HN"),
            seccion=seccion,
            puntaje=7 + (i % 4),
        )
        for i in range(1, n + 1)
    }


def _nota(item_id: int, **campos: Any) -> dict[str, Any]:
    base = {
        "item_id": item_id,
        "titular": f"Titular {item_id}",
        "resumen": "Resumen de dos líneas.",
        "por_que_te_sirve": "Porque sí.",
    }
    return base | campos


def _diario(*secciones: tuple[str, list[dict[str, Any]]]) -> str:
    return json.dumps({"secciones": [{"seccion": s, "notas": n} for s, n in secciones]})


def test_diario_valido_completa_url_y_fuentes_desde_la_base() -> None:
    texto = _diario(("ia", [_nota(1), _nota(2)]))
    diario = parsear_diario(texto, _candidatos())

    assert diario.cantidad_notas == 2
    seccion = diario.secciones[0]
    assert (seccion.clave, seccion.nombre) == ("ia", "IA aplicada")
    assert seccion.notas[0].url == "https://ejemplo.com/1"
    assert seccion.notas[0].fuentes == ["Blog", "HN"]


def test_diario_ignora_url_que_mande_el_modelo() -> None:
    texto = _diario(("ia", [_nota(1, url="https://inventada.com")]))
    assert parsear_diario(texto, _candidatos()).secciones[0].notas[0].url == "https://ejemplo.com/1"


def test_diario_ordena_secciones_segun_el_perfil() -> None:
    candidatos = _candidatos(3)
    texto = _diario(("general", [_nota(1)]), ("python", [_nota(2)]), ("ia", [_nota(3)]))
    diario = parsear_diario(texto, candidatos)
    assert [s.clave for s in diario.secciones] == ["ia", "python", "general"]


def test_diario_junta_secciones_repetidas_y_resuelve_nombres() -> None:
    texto = _diario(("ia", [_nota(1)]), ("IA aplicada", [_nota(2)]))
    diario = parsear_diario(texto, _candidatos())
    assert len(diario.secciones) == 1
    assert [n.item_id for n in diario.secciones[0].notas] == [1, 2]


def test_diario_seccion_desconocida_usa_la_del_puntaje() -> None:
    texto = _diario(("Miscelánea", [_nota(1)]))
    diario = parsear_diario(texto, _candidatos(seccion="dotnet"))
    assert diario.secciones[0].clave == "dotnet"


def test_diario_descarta_notas_invalidas_desconocidas_o_repetidas(
    caplog: pytest.LogCaptureFixture,
) -> None:
    texto = _diario(
        (
            "ia",
            [
                _nota(1),
                _nota(1),  # repetida
                _nota(99),  # no era candidata
                _nota(2, titular=""),  # vacía
                {"item_id": 3},  # incompleta
                _nota(3),
            ],
        )
    )
    with caplog.at_level(logging.WARNING):
        diario = parsear_diario(texto, _candidatos())

    assert [n.item_id for n in diario.secciones[0].notas] == [1, 3]
    assert len(caplog.records) == 4


def test_diario_sin_notas_validas_es_error() -> None:
    with pytest.raises(ErrorRespuestaLLM, match="ninguna nota"):
        parsear_diario(_diario(("ia", [_nota(99)])), _candidatos())


def test_diario_con_formato_roto_es_error() -> None:
    with pytest.raises(ErrorRespuestaLLM):
        parsear_diario('{"notas": []}', _candidatos())


def test_diario_con_demasiadas_notas_se_queda_con_las_de_mejor_puntaje() -> None:
    candidatos = _candidatos(20)
    texto = _diario(("ia", [_nota(i) for i in range(1, 21)]))
    diario = parsear_diario(texto, candidatos)

    ids = [n.item_id for n in diario.secciones[0].notas]
    assert len(ids) == MAX_NOTAS
    assert ids == sorted(ids)  # conserva el orden del modelo
    peor_que_quedo = min(candidatos[i].puntaje for i in ids)
    peor_afuera = max(candidatos[i].puntaje for i in candidatos if i not in ids)
    assert peor_que_quedo >= peor_afuera


def test_diario_se_serializa_a_json_para_la_base() -> None:
    diario = parsear_diario(_diario(("ia", [_nota(1)])), _candidatos())
    datos = diario.model_dump(mode="json")
    assert datos["secciones"][0]["notas"][0]["url"] == "https://ejemplo.com/1"
    assert "cantidad_notas" not in datos  # la property no se guarda
