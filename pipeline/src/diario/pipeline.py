"""Orquestación de las etapas del pipeline."""

import logging
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime

import httpx

from diario.config import Fuente
from diario.dedupe import agrupar
from diario.fuentes import ErrorFuente, traer_items
from diario.fuentes.articulos import descargar_textos
from diario.llm.cliente import (
    ClienteLLM,
    ConsumoTokens,
    Effort,
    ErrorLLMTransitorio,
    RespuestaLLM,
)
from diario.llm.puntaje import (
    SCHEMA_PUNTAJE,
    ItemAPuntuar,
    armar_mensaje,
    armar_system,
    parsear_puntaje,
)
from diario.llm.respuesta import ErrorRespuestaLLM
from diario.modelos import ItemCrudo
from diario.repositorio import Repositorio

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ResumenIngesta:
    items_traidos: int = 0
    grupos: int = 0
    items_nuevos: int = 0
    apariciones_nuevas: int = 0
    errores: list[dict[str, str]] = field(default_factory=list)


def traer_todas(
    fuentes: Sequence[Fuente], cliente: httpx.Client, desde: datetime
) -> tuple[list[ItemCrudo], list[dict[str, str]]]:
    """Trae todas las fuentes en paralelo. Una fuente que falla no corta las demás."""

    def traer_una(fuente: Fuente) -> list[ItemCrudo] | dict[str, str]:
        try:
            items = traer_items(fuente, cliente, desde)
        except (httpx.HTTPError, ErrorFuente) as e:
            logger.warning("Fuente %s falló: %s", fuente.nombre, e)
            return {"fuente": fuente.nombre, "error": f"{type(e).__name__}: {e}"}
        except Exception as e:
            # Un bug en un parser: lo registramos con traceback y seguimos.
            logger.exception("Error inesperado en la fuente %s", fuente.nombre)
            return {"fuente": fuente.nombre, "error": f"{type(e).__name__}: {e}"}
        logger.info("%-24s %3d items", fuente.nombre, len(items))
        return items

    items: list[ItemCrudo] = []
    errores: list[dict[str, str]] = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        for resultado in pool.map(traer_una, fuentes):
            if isinstance(resultado, dict):
                errores.append(resultado)
            else:
                items.extend(resultado)
    return items, errores


@dataclass(slots=True)
class ResumenPuntaje:
    puntuados: int = 0
    aprobados: int = 0  # puntaje >= UMBRAL_DIARIO
    invalidos: int = 0  # respuesta que no se pudo usar: gasta un intento del item
    fallidos: int = 0  # error transitorio de la API: se reintenta en otra corrida
    consumo: ConsumoTokens = field(default_factory=ConsumoTokens)


UMBRAL_DIARIO = 7
_MAX_TOKENS_PUNTAJE = 1024  # el thinking adaptativo también cuenta acá
_EFFORT_PUNTAJE: Effort = "low"  # clasificación: no necesita pensar mucho


def puntuar(
    repo: Repositorio,
    llm: ClienteLLM,
    items: Sequence[ItemAPuntuar],
    *,
    perfil: str,
    modelo: str,
    hilos: int,
) -> ResumenPuntaje:
    """Puntúa cada item con el LLM y guarda el resultado apenas llega.

    Guardar de a uno hace que un corte a mitad de camino no tire tokens ya
    gastados: la próxima corrida sigue con los que faltan.
    """
    resumen = ResumenPuntaje()
    if not items:
        return resumen
    system = armar_system(perfil)

    def llamar(item: ItemAPuntuar) -> RespuestaLLM | ErrorLLMTransitorio:
        try:
            return llm.pedir_json(
                modelo=modelo,
                system=system,
                mensaje=armar_mensaje(item),
                schema=SCHEMA_PUNTAJE,
                max_tokens=_MAX_TOKENS_PUNTAJE,
                effort=_EFFORT_PUNTAJE,
            )
        except ErrorLLMTransitorio as e:
            return e  # ErrorLLMFatal sí se propaga y corta todo

    def procesar(item: ItemAPuntuar, resultado: RespuestaLLM | ErrorLLMTransitorio) -> None:
        if isinstance(resultado, ErrorLLMTransitorio):
            logger.warning("Item %d sin puntuar por error de la API: %s", item.id, resultado)
            resumen.fallidos += 1
            return

        resumen.consumo += resultado.consumo
        try:
            if resultado.stop_reason in ("refusal", "max_tokens"):
                raise ErrorRespuestaLLM(f"stop_reason={resultado.stop_reason}")
            p = parsear_puntaje(resultado.texto, area_respaldo=item.area)
        except ErrorRespuestaLLM as e:
            logger.warning("Respuesta inválida para el item %d: %s", item.id, e)
            repo.registrar_intento_fallido(item.id)
            resumen.invalidos += 1
            return

        repo.guardar_puntaje(item.id, p.puntaje, p.seccion, p.motivo)
        resumen.puntuados += 1
        resumen.aprobados += p.puntaje >= UMBRAL_DIARIO
        logger.debug("%2d %-10s %s", p.puntaje, p.seccion, item.titulo)

    # La primera llamada va sola: escribe el system prompt en caché y las demás
    # lo leen. Si salieran todas juntas, todas pagarían la escritura completa.
    primero, *resto = items
    procesar(primero, llamar(primero))

    with ThreadPoolExecutor(max_workers=hilos) as pool:
        futuros = {pool.submit(llamar, item): item for item in resto}
        try:
            for futuro in as_completed(futuros):
                procesar(futuros[futuro], futuro.result())
        except BaseException:
            # Error fatal (o Ctrl+C): no seguir gastando en las llamadas pendientes.
            pool.shutdown(wait=False, cancel_futures=True)
            raise

    logger.info(
        "Puntaje: %d puntuados (%d con %d o más), %d inválidos, %d con error de API. %s",
        resumen.puntuados,
        resumen.aprobados,
        UMBRAL_DIARIO,
        resumen.invalidos,
        resumen.fallidos,
        resumen.consumo.resumen(modelo),
    )
    return resumen


@dataclass(frozen=True, slots=True)
class ResumenContenido:
    pendientes: int
    completados: int


def completar_contenido(
    repo: Repositorio, cliente: httpx.Client, *, max_contenido: int
) -> ResumenContenido:
    """Baja el artículo de los items que llegaron sin texto (la mayoría de HN).

    Solo toca items sin puntuar: como el puntaje se calcula en la misma
    corrida, un sitio que bloquea la descarga se intenta una sola vez.
    """
    pendientes = repo.items_sin_contenido()
    if not pendientes:
        return ResumenContenido(pendientes=0, completados=0)

    textos = descargar_textos(cliente, [url for _, url in pendientes])
    completados = repo.actualizar_contenidos(
        [(item_id, texto) for (item_id, _), texto in zip(pendientes, textos, strict=True)],
        max_contenido,
    )
    logger.info("Contenido: %d de %d items sin texto completados", completados, len(pendientes))
    return ResumenContenido(pendientes=len(pendientes), completados=completados)


def ingestar(
    repo: Repositorio,
    fuentes: Sequence[Fuente],
    cliente: httpx.Client,
    *,
    desde: datetime,
    dias_dedupe: int,
    max_contenido: int,
) -> ResumenIngesta:
    items, errores = traer_todas(fuentes, cliente, desde)
    existentes = repo.referencias_recientes(dias_dedupe)
    grupos = agrupar(items, existentes)
    guardado = repo.guardar_grupos(grupos, max_contenido)

    resumen = ResumenIngesta(
        items_traidos=len(items),
        grupos=len(grupos),
        items_nuevos=guardado.items_nuevos,
        apariciones_nuevas=guardado.apariciones_nuevas,
        errores=errores,
    )
    logger.info(
        "Ingesta: %d items -> %d grupos -> %d nuevos (%d apariciones nuevas), %d fuentes con error",
        resumen.items_traidos,
        resumen.grupos,
        resumen.items_nuevos,
        resumen.apariciones_nuevas,
        len(errores),
    )
    return resumen
