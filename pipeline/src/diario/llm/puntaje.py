"""Puntaje de cada item con un modelo chico.

Formato que pedimos: {"puntaje": int 0-10, "seccion": str, "motivo": str}
"""

from dataclasses import dataclass

from pydantic import BaseModel, Field, ValidationError

from diario.llm.respuesta import ErrorRespuestaLLM, extraer_objeto_json
from diario.secciones import resolver_seccion

MAX_MOTIVO = 500


class _RespuestaPuntaje(BaseModel):
    # pydantic acepta "8" y 8.0 como 8, pero rechaza 7.5: no inventamos redondeos.
    puntaje: int = Field(ge=0, le=10)
    seccion: str | None = None
    motivo: str = Field(min_length=1)


@dataclass(frozen=True, slots=True)
class Puntaje:
    puntaje: int
    seccion: str  # siempre una clave válida de SECCIONES
    motivo: str


def parsear_puntaje(texto: str, *, area_respaldo: str) -> Puntaje:
    """Valida la respuesta del modelo.

    Si la sección no es una de las conocidas, usamos el área de la fuente: es
    un error menor que no justifica pagar otra llamada.
    """
    datos = extraer_objeto_json(texto)
    try:
        r = _RespuestaPuntaje.model_validate(datos)
    except ValidationError as e:
        raise ErrorRespuestaLLM(f"Puntaje con formato inválido: {e}") from e

    motivo = r.motivo.strip()
    if len(motivo) > MAX_MOTIVO:
        motivo = motivo[: MAX_MOTIVO - 1] + "…"

    return Puntaje(
        puntaje=r.puntaje,
        seccion=resolver_seccion(r.seccion, respaldo=area_respaldo),
        motivo=motivo,
    )
