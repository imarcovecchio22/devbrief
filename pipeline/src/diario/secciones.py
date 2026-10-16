"""Secciones del diario: lista cerrada, en el orden en que se muestran.

Las claves coinciden con los valores de `area` en fuentes.yaml (hay un test
que lo verifica). El orden sigue los pesos de config/perfil.md.
"""

import re
import unicodedata

SECCIONES: dict[str, str] = {
    "ia": "IA aplicada",
    "dotnet": ".NET y C#",
    "python": "Python",
    "web": "Stack web",
    "repos": "Repos y herramientas",
    "general": "Desarrollo en general",
    "php": "PHP y Laravel",
    "gamedev": "Game dev web",
    "automatizaciones": "Automatizaciones",
    "trading": "Trading algorítmico",
    "impresion3d": "Impresión 3D",
}

SECCION_POR_DEFECTO = "general"


def _clave(texto: str) -> str:
    # "Impresión 3D" -> "impresion3d"; ".NET y C#" -> "netyc"
    sin_tildes = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", sin_tildes.lower())


# Acepta tanto la clave ("dotnet") como el nombre visible (".NET y C#").
_ALIAS: dict[str, str] = {_clave(k): k for k in SECCIONES} | {
    _clave(v): k for k, v in SECCIONES.items()
}


def resolver_seccion(valor: str | None, *, respaldo: str = SECCION_POR_DEFECTO) -> str:
    """Devuelve la clave de sección para `valor`, o `respaldo` si no se reconoce."""
    if valor:
        encontrada = _ALIAS.get(_clave(valor))
        if encontrada is not None:
            return encontrada
    return respaldo if respaldo in SECCIONES else SECCION_POR_DEFECTO


def orden(seccion: str) -> int:
    """Posición de la sección para ordenar el diario."""
    return list(SECCIONES).index(seccion) if seccion in SECCIONES else len(SECCIONES)
