"""Redacción del diario: parseo puro y etapa completa con un LLM falso."""

import json
import logging
from datetime import UTC, date, datetime
from typing import Any

import pytest

from diario.dedupe import agrupar
from diario.llm.cliente import ConsumoTokens, Effort, RespuestaLLM
from diario.llm.redaccion import (
    MAX_NOTAS,
    SCHEMA_DIARIO,
    Candidato,
    armar_mensaje,
    parsear_diario,
)
from diario.llm.respuesta import ErrorRespuestaLLM
from diario.modelos import ItemCrudo
from diario.pipeline import redactar
from diario.repositorio import Repositorio
from diario.secciones import SECCIONES

HOY = date(2026, 10, 16)


def _candidato(item_id: int, puntaje: int = 7, seccion: str = "dotnet", **campos: Any) -> Candidato:
    base: dict[str, Any] = {
        "item_id": item_id,
        "titulo": f"Título {item_id}",
        "url": f"https://ejemplo.com/{item_id}",
        "contenido": "Contenido.",
        "fuentes": ("Blog",),
        "seccion": seccion,
        "puntaje": puntaje,
        "motivo": "Motivo.",
    }
    return Candidato(**(base | campos))


def _mapa(*candidatos: Candidato) -> dict[int, Candidato]:
    return {c.item_id: c for c in candidatos}


def _nota(*ids: int, **campos: Any) -> dict[str, Any]:
    base = {
        "item_ids": list(ids),
        "titular": f"Titular {ids[0]}",
        "resumen": "Resumen de dos líneas.",
        "por_que_te_sirve": "Porque sí.",
    }
    return base | campos


def _diario(
    *secciones: tuple[str, list[dict[str, Any]]], radar: list[dict[str, Any]] | None = None
) -> str:
    return json.dumps(
        {
            "secciones": [{"seccion": s, "notas": n} for s, n in secciones],
            "radar": radar or [],
        }
    )


# ---------- schema y prompt ----------


def test_schema_ofrece_exactamente_las_secciones() -> None:
    seccion = SCHEMA_DIARIO["properties"]["secciones"]["items"]["properties"]["seccion"]
    assert seccion["enum"] == list(SECCIONES)


def test_mensaje_marca_las_candidatas_del_radar() -> None:
    mensaje = armar_mensaje(
        [_candidato(1, 8, "dotnet"), _candidato(2, 5, "ia_global"), _candidato(3, 6, "web")],
        HOY,
    )
    assert mensaje.startswith("Diario del 2026-10-16.")
    assert '<candidata id="1" puntaje="8" seccion="dotnet" radar="no">' in mensaje
    assert '<candidata id="2" puntaje="5" seccion="ia_global" radar="si">' in mensaje
    assert '<candidata id="3" puntaje="6" seccion="web" radar="no">' in mensaje


def test_mensaje_recorta_el_contenido_de_cada_candidata() -> None:
    mensaje = armar_mensaje([_candidato(1, contenido="x" * 5000)], HOY)
    assert "x" * 1200 in mensaje
    assert "x" * 1201 not in mensaje


# ---------- parsear_diario ----------


def test_diario_valido_completa_url_y_fuentes_desde_la_base() -> None:
    candidatos = _mapa(_candidato(1), _candidato(2))
    diario = parsear_diario(_diario(("dotnet", [_nota(1), _nota(2)])), candidatos, HOY)

    assert diario.fecha == HOY
    assert diario.cantidad_notas == 2
    seccion = diario.secciones[0]
    assert (seccion.clave, seccion.nombre) == ("dotnet", ".NET y C#")
    assert seccion.notas[0].url == "https://ejemplo.com/1"
    assert seccion.notas[0].fuentes == ["Blog"]


def test_nota_que_fusiona_varias_candidatas() -> None:
    candidatos = _mapa(
        _candidato(1, 8, "ia_global", fuentes=("The Decoder",)),
        _candidato(2, 7, "ia_global", fuentes=("Hugging Face Blog", "The Decoder")),
        _candidato(3, 7, "ia_global", fuentes=("Hacker News portada",)),
    )
    diario = parsear_diario(_diario(("ia_global", [_nota(1, 2, 3)])), candidatos, HOY)

    [nota] = diario.secciones[0].notas
    assert nota.item_ids == [1, 2, 3]
    assert nota.url == "https://ejemplo.com/1"  # la de la primera
    assert nota.fuentes == ["The Decoder", "Hugging Face Blog", "Hacker News portada"]
    assert sorted(diario.item_ids) == [1, 2, 3]


def test_diario_ignora_url_que_mande_el_modelo() -> None:
    texto = _diario(("dotnet", [_nota(1, url="https://inventada.com")]))
    diario = parsear_diario(texto, _mapa(_candidato(1)), HOY)
    assert diario.secciones[0].notas[0].url == "https://ejemplo.com/1"


def test_diario_ordena_secciones_segun_el_perfil() -> None:
    candidatos = _mapa(_candidato(1), _candidato(2), _candidato(3))
    texto = _diario(("general", [_nota(1)]), ("python", [_nota(2)]), ("ia_global", [_nota(3)]))
    diario = parsear_diario(texto, candidatos, HOY)
    assert [s.clave for s in diario.secciones] == ["ia_global", "python", "general"]


def test_diario_seccion_desconocida_usa_la_del_puntaje() -> None:
    texto = _diario(("Miscelánea", [_nota(1)]))
    diario = parsear_diario(texto, _mapa(_candidato(1, seccion="espacio")), HOY)
    assert diario.secciones[0].clave == "espacio"


def test_ids_repetidos_o_desconocidos_se_descartan(caplog: pytest.LogCaptureFixture) -> None:
    candidatos = _mapa(_candidato(1), _candidato(2), _candidato(3))
    texto = _diario(
        (
            "dotnet",
            [
                _nota(1),
                _nota(1, 2),  # el 1 ya se usó: la nota queda solo con el 2
                _nota(99),  # no era candidato: la nota se descarta
                _nota(3, titular=""),  # vacía
            ],
        )
    )
    with caplog.at_level(logging.WARNING):
        diario = parsear_diario(texto, candidatos, HOY)

    assert [n.item_ids for n in diario.secciones[0].notas] == [[1], [2]]
    assert len(caplog.records) == 3


def test_diario_sin_notas_validas_es_error() -> None:
    with pytest.raises(ErrorRespuestaLLM, match="ninguna nota"):
        parsear_diario(_diario(("dotnet", [_nota(99)])), _mapa(_candidato(1)), HOY)


def test_diario_con_formato_roto_es_error() -> None:
    with pytest.raises(ErrorRespuestaLLM):
        parsear_diario('{"notas": []}', _mapa(_candidato(1)), HOY)


def test_demasiadas_notas_quedan_las_de_mejor_puntaje() -> None:
    candidatos = _mapa(*(_candidato(i, 6 + i % 4) for i in range(1, 21)))
    texto = _diario(("dotnet", [_nota(i) for i in range(1, 21)]))
    diario = parsear_diario(texto, candidatos, HOY)

    ids = [n.item_ids[0] for n in diario.secciones[0].notas]
    assert len(ids) == MAX_NOTAS
    assert ids == sorted(ids)  # conserva el orden del modelo
    peor_que_quedo = min(candidatos[i].puntaje for i in ids)
    peor_afuera = max(candidatos[i].puntaje for i in candidatos if i not in ids)
    assert peor_que_quedo >= peor_afuera


# ---------- radar ----------


def test_radar_del_modelo_completa_url_y_fuentes() -> None:
    candidatos = _mapa(_candidato(1), _candidato(2, 5, "robotica", fuentes=("The Robot Report",)))
    texto = _diario(
        ("dotnet", [_nota(1)]), radar=[{"item_ids": [2], "linea": "Un humanoide nuevo."}]
    )
    diario = parsear_diario(texto, candidatos, HOY)

    [entrada] = diario.radar
    assert (entrada.linea, entrada.url, entrada.fuentes) == (
        "Un humanoide nuevo.",
        "https://ejemplo.com/2",
        ["The Robot Report"],
    )
    assert entrada.seccion == "robotica"


def test_radar_agrega_lo_que_el_modelo_olvido() -> None:
    candidatos = _mapa(
        _candidato(1),
        _candidato(2, 5, "ia_global", titulo="DeepSeek lanza un modelo"),
        _candidato(3, 5, "espacio", titulo="Nuevo satélite"),
        _candidato(4, 6, "web"),  # no es de IA/robótica/espacio: no va al radar
    )
    texto = _diario(("dotnet", [_nota(1)]), radar=[{"item_ids": [3], "linea": "Satélite."}])
    diario = parsear_diario(texto, candidatos, HOY)

    assert [(r.item_ids, r.linea) for r in diario.radar] == [
        ([2], "DeepSeek lanza un modelo"),  # agregado con su título original
        ([3], "Satélite."),
    ]  # ordenado por sección: ia_global antes que espacio
    assert 4 not in diario.item_ids


def test_notas_recortadas_de_ia_pasan_al_radar() -> None:
    candidatos = _mapa(*(_candidato(i, 7, "ia_global") for i in range(1, 18)))
    candidatos[17] = _candidato(17, 7, "ia_global", titulo="La que no entró")
    texto = _diario(("ia_global", [_nota(i) for i in range(1, 18)]))
    diario = parsear_diario(texto, candidatos, HOY)

    assert diario.cantidad_notas == MAX_NOTAS
    assert {i for r in diario.radar for i in r.item_ids} == {16, 17}
    assert sorted(diario.item_ids) == list(range(1, 18))


def test_diario_se_serializa_a_json_para_la_base() -> None:
    diario = parsear_diario(_diario(("dotnet", [_nota(1)])), _mapa(_candidato(1)), HOY)
    datos = diario.model_dump(mode="json")
    assert datos["fecha"] == "2026-10-16"
    assert datos["secciones"][0]["notas"][0]["url"] == "https://ejemplo.com/1"
    assert datos["radar"] == []
    assert "cantidad_notas" not in datos  # las properties no se guardan


# ---------- etapa (integración con la base de test) ----------


class LLMFalso:
    """Devuelve un diario con una nota por cada candidata de puntaje 6 o más."""

    def __init__(self) -> None:
        self.llamadas = 0

    def pedir_json(
        self,
        *,
        modelo: str,
        system: str,
        mensaje: str,
        schema: dict[str, Any],
        max_tokens: int,
        effort: Effort,
    ) -> RespuestaLLM:
        self.llamadas += 1
        ids = [
            int(parte.split('"')[1])
            for parte in mensaje.split("<candidata id=")[1:]
            if 'radar="no"' in parte.split(">")[0] or 'puntaje="5"' not in parte.split(">")[0]
        ]
        texto = _diario(("general", [_nota(i) for i in ids]))
        return RespuestaLLM(texto, "end_turn", ConsumoTokens(entrada=5000, salida=800, llamadas=1))


def _cargar(repo: Repositorio, puntajes: dict[str, tuple[int, str]]) -> None:
    items = [
        ItemCrudo(
            fuente="Blog",
            area="general",
            url=f"https://blog.com/{t}",
            titulo=t,
            contenido=f"contenido de {t}",
            fecha_publicacion=datetime(2026, 10, 15, tzinfo=UTC),
        )
        for t in puntajes
    ]
    repo.guardar_grupos(agrupar(items), max_contenido=2000)
    for titulo, (puntaje, seccion) in puntajes.items():
        repo._db.execute(
            "UPDATE items SET puntaje = %s, seccion = %s, motivo = 'x', puntuado_en = now() "
            "WHERE titulo = %s",
            (puntaje, seccion, titulo),
        )


def _correr(repo: Repositorio, llm: LLMFalso, *, forzar: bool = False) -> Any:
    return redactar(repo, llm, perfil="Perfil", modelo="m", fecha=HOY, dias=3, forzar=forzar)


def _publicados(repo: Repositorio) -> dict[str, bool]:
    filas = repo._db.execute("SELECT titulo, diario_id IS NOT NULL FROM items").fetchall()
    return dict(filas)


def test_redactar_guarda_el_diario_y_marca_los_items(repo: Repositorio) -> None:
    _cargar(
        repo,
        {
            "nota": (8, "dotnet"),
            "relleno": (6, "web"),
            "radar": (5, "robotica"),
            "afuera": (4, "ia_global"),
            "bajo": (5, "web"),
        },
    )
    llm = LLMFalso()

    resumen = _correr(repo, llm)

    assert (resumen.notas, resumen.radar, resumen.candidatos) == (2, 1, 3)
    assert _publicados(repo) == {
        "nota": True,
        "relleno": True,
        "radar": True,
        "afuera": False,
        "bajo": False,
    }
    contenido = repo._db.execute("SELECT contenido FROM diarios").fetchone()
    assert contenido is not None
    assert contenido[0]["fecha"] == "2026-10-16"
    assert len(contenido[0]["radar"]) == 1


def test_redactar_es_idempotente(repo: Repositorio) -> None:
    _cargar(repo, {"a": (8, "dotnet")})
    llm = LLMFalso()
    _correr(repo, llm)
    segunda = _correr(repo, llm)

    assert llm.llamadas == 1
    assert segunda.salteado is not None
    assert "ya existe" in segunda.salteado


def test_redactar_forzado_reemplaza_el_diario_del_dia(repo: Repositorio) -> None:
    _cargar(repo, {"a": (8, "dotnet"), "b": (7, "web")})
    llm = LLMFalso()
    primero = _correr(repo, llm)
    segundo = _correr(repo, llm, forzar=True)

    assert llm.llamadas == 2
    assert segundo.notas == primero.notas == 2  # vuelve a usar los mismos items
    filas = repo._db.execute("SELECT count(*) FROM diarios").fetchone()
    assert filas == (1,)
    assert all(_publicados(repo).values())


def test_sin_candidatas_no_hay_diario(repo: Repositorio) -> None:
    _cargar(repo, {"a": (5, "robotica"), "b": (3, "dotnet")})
    llm = LLMFalso()
    resumen = _correr(repo, llm)

    assert llm.llamadas == 0
    assert resumen.salteado is not None
    assert resumen.diario_id is None
