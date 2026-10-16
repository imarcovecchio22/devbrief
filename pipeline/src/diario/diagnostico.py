"""Prueba todas las fuentes configuradas e informa cuáles fallan."""

import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

import httpx

from diario.config import Fuente
from diario.fuentes import tiene_fetcher, traer_items


class Estado(StrEnum):
    OK = "OK"
    VACIA = "VACÍA"  # respondió bien pero sin items en la ventana
    FALLA = "FALLA"
    SIN_FETCHER = "SIN FETCHER"


@dataclass(frozen=True, slots=True)
class ResultadoPrueba:
    fuente: Fuente
    estado: Estado
    cantidad: int = 0
    segundos: float = 0.0
    detalle: str = ""


def probar_fuente(fuente: Fuente, cliente: httpx.Client, desde: datetime) -> ResultadoPrueba:
    if not tiene_fetcher(fuente):
        return ResultadoPrueba(fuente, Estado.SIN_FETCHER, detalle="se implementa en V2")

    inicio = time.perf_counter()
    try:
        items = traer_items(fuente, cliente, desde)
    # Acá sí atrapamos todo: un bug en un parser tiene que verse como FALLA
    # de esa fuente, no cortar el diagnóstico de las demás.
    except Exception as e:
        return ResultadoPrueba(
            fuente,
            Estado.FALLA,
            segundos=time.perf_counter() - inicio,
            detalle=f"{type(e).__name__}: {e}",
        )

    return ResultadoPrueba(
        fuente,
        Estado.OK if items else Estado.VACIA,
        cantidad=len(items),
        segundos=time.perf_counter() - inicio,
        detalle=items[0].titulo if items else "",
    )


def probar_fuentes(
    fuentes: list[Fuente], cliente: httpx.Client, desde: datetime, *, hilos: int = 8
) -> list[ResultadoPrueba]:
    """Prueba en paralelo (la espera es de red, así que los hilos rinden).

    Devuelve los resultados en el mismo orden que `fuentes`.
    """
    with ThreadPoolExecutor(max_workers=hilos) as pool:
        return list(pool.map(lambda f: probar_fuente(f, cliente, desde), fuentes))
