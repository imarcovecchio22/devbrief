"""Extracción de JSON de las respuestas del modelo.

Aunque le pidamos "solo JSON", a veces el modelo lo envuelve en un bloque
```json``` o agrega una frase antes. Toleramos eso; cualquier otra cosa es error.
"""

import json
import re
from typing import Any

_BLOQUE_CODIGO = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL | re.IGNORECASE)


class ErrorRespuestaLLM(Exception):
    """La respuesta del modelo no tiene el formato esperado."""


def extraer_objeto_json(texto: str) -> dict[str, Any]:
    candidato = texto.strip()

    bloque = _BLOQUE_CODIGO.search(candidato)
    if bloque is not None:
        candidato = bloque.group(1)
    else:
        # Texto alrededor del JSON: nos quedamos de la primera { a la última }.
        inicio, fin = candidato.find("{"), candidato.rfind("}")
        if inicio != -1 and fin > inicio:
            candidato = candidato[inicio : fin + 1]

    try:
        datos = json.loads(candidato)
    except json.JSONDecodeError as e:
        raise ErrorRespuestaLLM(f"JSON inválido: {e}. Respuesta: {_muestra(texto)}") from e

    if not isinstance(datos, dict):
        raise ErrorRespuestaLLM(f"Se esperaba un objeto JSON. Respuesta: {_muestra(texto)}")
    return datos


def _muestra(texto: str, largo: int = 200) -> str:
    return repr(texto[:largo] + ("…" if len(texto) > largo else ""))
