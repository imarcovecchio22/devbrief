"""Orquestación de las etapas del pipeline."""

import logging
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime

import httpx

from diario.config import Fuente
from diario.dedupe import agrupar
from diario.fuentes import ErrorFuente, traer_items
from diario.fuentes.articulos import descargar_textos
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
