"""Redacción del diario con un modelo mejor.

El modelo recibe los candidatos (con su `item_id`) y devuelve:

    {"secciones": [{"seccion": "ia", "notas": [
        {"item_id": 12, "titular": "...", "resumen": "...", "por_que_te_sirve": "..."}
    ]}]}

La URL y las fuentes NO se le piden: se completan desde la base por `item_id`,
así es imposible que aparezca un link inventado.
"""

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from diario.llm.respuesta import ErrorRespuestaLLM, extraer_objeto_json
from diario.secciones import SECCIONES, orden, resolver_seccion

logger = logging.getLogger(__name__)

MAX_NOTAS = 15


@dataclass(frozen=True, slots=True)
class Candidato:
    """Un item puntuado que se le ofrece al modelo para el diario."""

    item_id: int
    url: str
    fuentes: tuple[str, ...]
    seccion: str
    puntaje: int


# ---------- lo que se guarda en diarios.contenido (y lee la web) ----------


class Nota(BaseModel):
    item_id: int
    titular: str
    resumen: str
    por_que_te_sirve: str
    url: str
    fuentes: list[str]


class Seccion(BaseModel):
    clave: str
    nombre: str
    notas: list[Nota]


class Diario(BaseModel):
    secciones: list[Seccion]

    @property
    def cantidad_notas(self) -> int:
        return sum(len(s.notas) for s in self.secciones)


# ---------- lo que devuelve el modelo ----------


class _NotaLLM(BaseModel):
    item_id: int
    titular: str = Field(min_length=1)
    resumen: str = Field(min_length=1)
    por_que_te_sirve: str = Field(min_length=1)


class _SeccionLLM(BaseModel):
    seccion: str | None = None
    # Las notas se validan una por una: una nota rota no tira el diario entero.
    notas: list[dict[str, Any]]


class _DiarioLLM(BaseModel):
    secciones: list[_SeccionLLM]


def parsear_diario(texto: str, candidatos: Mapping[int, Candidato]) -> Diario:
    """Valida la respuesta del modelo y la combina con los datos de la base.

    - Notas mal formadas, con `item_id` desconocido o repetido: se descartan.
    - Sección desconocida: se usa la que asignó el puntaje.
    - Más de MAX_NOTAS: se quedan las de mejor puntaje.
    - Si no queda ninguna nota válida: ErrorRespuestaLLM.
    """
    datos = extraer_objeto_json(texto)
    try:
        respuesta = _DiarioLLM.model_validate(datos)
    except ValidationError as e:
        raise ErrorRespuestaLLM(f"Diario con formato inválido: {e}") from e

    # (clave de sección, nota, puntaje) en el orden en que vinieron
    elegidas: list[tuple[str, Nota, int]] = []
    vistos: set[int] = set()

    for seccion_llm in respuesta.secciones:
        for crudo in seccion_llm.notas:
            try:
                nota_llm = _NotaLLM.model_validate(crudo)
            except ValidationError as e:
                logger.warning("Nota descartada (formato): %s", e.errors()[0]["msg"])
                continue

            candidato = candidatos.get(nota_llm.item_id)
            if candidato is None:
                logger.warning("Nota descartada: item_id %s no era candidato", nota_llm.item_id)
                continue
            if nota_llm.item_id in vistos:
                logger.warning("Nota descartada: item_id %s repetido", nota_llm.item_id)
                continue
            vistos.add(nota_llm.item_id)

            clave = resolver_seccion(seccion_llm.seccion, respaldo=candidato.seccion)
            nota = Nota(
                item_id=candidato.item_id,
                titular=nota_llm.titular.strip(),
                resumen=nota_llm.resumen.strip(),
                por_que_te_sirve=nota_llm.por_que_te_sirve.strip(),
                url=candidato.url,
                fuentes=list(candidato.fuentes),
            )
            elegidas.append((clave, nota, candidato.puntaje))

    if not elegidas:
        raise ErrorRespuestaLLM("El diario no tiene ninguna nota válida")

    if len(elegidas) > MAX_NOTAS:
        logger.warning("El modelo devolvió %d notas; se recorta a %d", len(elegidas), MAX_NOTAS)
        # sorted es estable: a igual puntaje gana la que el modelo puso antes
        por_puntaje = sorted(range(len(elegidas)), key=lambda i: -elegidas[i][2])
        quedan = set(por_puntaje[:MAX_NOTAS])
        elegidas = [e for i, e in enumerate(elegidas) if i in quedan]

    return _armar(elegidas)


def _armar(elegidas: list[tuple[str, Nota, int]]) -> Diario:
    por_seccion: dict[str, list[Nota]] = {}
    for clave, nota, _ in elegidas:
        por_seccion.setdefault(clave, []).append(nota)

    return Diario(
        secciones=[
            Seccion(clave=clave, nombre=SECCIONES[clave], notas=notas)
            for clave, notas in sorted(por_seccion.items(), key=lambda kv: orden(kv[0]))
        ]
    )
