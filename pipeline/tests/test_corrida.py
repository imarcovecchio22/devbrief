"""Corrida completa de punta a punta con red y LLM falsos, contra la base de test."""

import json
import re
from datetime import UTC, date, datetime
from typing import Any

import httpx

from diario.config import Fuente, FuenteRss
from diario.llm.cliente import ConsumoTokens, Effort, ErrorLLMFatal, RespuestaLLM
from diario.pipeline import ResumenCorrida, correr_todo
from diario.repositorio import Repositorio
from diario.settings import Settings

HOY = date(2026, 10, 16)
HTML = {"content-type": "text/html; charset=utf-8"}


def _feed(*titulos: str) -> bytes:
    ahora = datetime.now(UTC).strftime("%a, %d %b %Y %H:%M:%S +0000")
    items = "".join(
        f"<item><title>{t}</title><link>https://blog.com/{t}</link>"
        f"<pubDate>{ahora}</pubDate><description>Texto de {t}</description></item>"
        for t in titulos
    )
    rss = (
        f'<?xml version="1.0"?><rss version="2.0"><channel><title>x</title>{items}</channel></rss>'
    )
    return rss.encode()


class LLMFalso:
    """Puntúa todo con 8 y escribe una nota por candidata. Puede fallar a pedido."""

    def __init__(self, fallar_en: str | None = None) -> None:
        self.fallar_en = fallar_en
        self.llamadas: list[str] = []

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
        etapa = "puntaje" if "evaluaciones" in schema["properties"] else "redaccion"
        self.llamadas.append(etapa)
        if etapa == self.fallar_en:
            raise ErrorLLMFatal("Se agotó el cupo de la suscripción")

        consumo = ConsumoTokens(entrada=1000, salida=100, llamadas=1)
        if etapa == "puntaje":
            ids = [int(i) for i in re.findall(r'<noticia id="(\d+)">', mensaje)]
            evaluaciones = [
                {"id": i, "motivo": "Útil.", "seccion": "dotnet", "puntaje": 8} for i in ids
            ]
            return RespuestaLLM(json.dumps({"evaluaciones": evaluaciones}), "end_turn", consumo)

        ids = [int(i) for i in re.findall(r'<candidata id="(\d+)"', mensaje)]
        notas = [
            {"item_ids": [i], "titular": "T", "resumen": "R", "por_que_te_sirve": "P"} for i in ids
        ]
        diario = {"secciones": [{"seccion": "dotnet", "notas": notas}], "radar": []}
        return RespuestaLLM(json.dumps(diario), "end_turn", consumo)


def _cliente_http(feed: bytes) -> httpx.Client:
    def responder(request: httpx.Request) -> httpx.Response:
        if request.url.host == "caida.com":
            return httpx.Response(503)
        if request.url.path == "/feed":
            return httpx.Response(200, content=feed)
        return httpx.Response(200, text="<article>Cuerpo</article>", headers=HTML)

    return httpx.Client(transport=httpx.MockTransport(responder))


FUENTES: list[Fuente] = [
    FuenteRss(nombre="Blog", tipo="rss", url="https://blog.com/feed", area="dotnet"),
    FuenteRss(nombre="Caída", tipo="rss", url="https://caida.com/feed", area="dotnet"),
]


def _correr(repo: Repositorio, llm: LLMFalso, feed: bytes) -> ResumenCorrida:
    settings = Settings(ventana_dias=3, tamano_lote_puntaje=20, hilos_llm=2)
    with _cliente_http(feed) as cliente:
        return correr_todo(
            repo, cliente, llm, FUENTES, settings=settings, perfil="Perfil", fecha=HOY
        )


def test_corrida_completa_genera_el_diario(repo: Repositorio) -> None:
    llm = LLMFalso()
    r = _correr(repo, llm, _feed("a", "b", "c"))

    assert not r.fallo
    assert r.ingesta is not None and r.ingesta.items_nuevos == 3
    assert r.puntaje is not None and r.puntaje.puntuados == 3
    assert r.redaccion is not None and r.redaccion.notas == 3
    assert llm.llamadas == ["puntaje", "redaccion"]
    # la fuente caída queda registrada, pero no cuenta como falla
    assert [e["fuente"] for e in r.errores] == ["Caída"]
    assert r.consumo.llamadas == 2


def test_segunda_corrida_del_dia_no_gasta_tokens_ni_duplica(repo: Repositorio) -> None:
    feed = _feed("a", "b")
    _correr(repo, LLMFalso(), feed)

    llm = LLMFalso()
    r = _correr(repo, llm, feed)

    assert llm.llamadas == []  # nada nuevo que puntuar y el diario ya existe
    assert r.ingesta is not None and r.ingesta.items_nuevos == 0
    assert r.redaccion is not None and r.redaccion.salteado is not None
    assert repo._db.execute("SELECT count(*) FROM diarios").fetchone() == (1,)


def test_lo_nuevo_del_mismo_dia_se_puntua_y_espera_al_diario_de_manana(
    repo: Repositorio,
) -> None:
    _correr(repo, LLMFalso(), _feed("a"))
    llm = LLMFalso()
    r = _correr(repo, llm, _feed("a", "nuevo"))

    assert llm.llamadas == ["puntaje"]  # solo el item nuevo; la redacción se saltea
    assert r.puntaje is not None and r.puntaje.puntuados == 1
    fila = repo._db.execute("SELECT diario_id FROM items WHERE titulo = 'nuevo'").fetchone()
    assert fila == (None,)


def test_cupo_agotado_en_el_puntaje_corta_antes_de_redactar(repo: Repositorio) -> None:
    llm = LLMFalso(fallar_en="puntaje")
    r = _correr(repo, llm, _feed("a", "b"))

    assert r.fallo
    assert llm.llamadas == ["puntaje"]
    assert r.redaccion is None
    assert {"etapa": "puntaje", "error": "Se agotó el cupo de la suscripción"} in r.errores
    # lo ingerido queda guardado y sin intentos gastados: la próxima corrida retoma
    filas = repo._db.execute("SELECT puntaje, intentos_puntaje FROM items").fetchall()
    assert filas == [(None, 0), (None, 0)]


def test_falla_en_la_redaccion_conserva_los_puntajes(repo: Repositorio) -> None:
    r = _correr(repo, LLMFalso(fallar_en="redaccion"), _feed("a"))

    assert r.fallo
    assert r.puntaje is not None and r.puntaje.puntuados == 1
    assert repo._db.execute("SELECT count(*) FROM diarios").fetchone() == (0,)

    # la siguiente corrida no vuelve a puntuar: solo redacta
    llm = LLMFalso()
    _correr(repo, llm, _feed("a"))
    assert llm.llamadas == ["redaccion"]
