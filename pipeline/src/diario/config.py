"""Carga y validación de config/fuentes.yaml."""

from pathlib import Path
from typing import Annotated, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, TypeAdapter, ValidationError


class _FuenteBase(BaseModel):
    # extra="forbid": un campo mal escrito en el YAML es un error, no se ignora en silencio.
    model_config = ConfigDict(extra="forbid", frozen=True)

    nombre: str
    area: str
    activa: bool = False


class FuenteRss(_FuenteBase):
    tipo: Literal["rss"]
    url: HttpUrl


class FuenteScrape(_FuenteBase):
    tipo: Literal["scrape"]
    url: HttpUrl


class FuenteHn(_FuenteBase):
    tipo: Literal["hn", "hn_show"]
    min_puntaje: int = 0


class FuenteReddit(_FuenteBase):
    tipo: Literal["reddit"]
    sub: str
    min_puntaje: int = 0


class FuenteGithubTrending(_FuenteBase):
    tipo: Literal["github_trending"]
    lenguajes: list[str] = []


# Unión discriminada: pydantic mira el campo `tipo` y elige la clase correcta.
type Fuente = Annotated[
    FuenteRss | FuenteScrape | FuenteHn | FuenteReddit | FuenteGithubTrending,
    Field(discriminator="tipo"),
]

_adaptador = TypeAdapter(list[Fuente])


class ErrorConfig(Exception):
    """El archivo de fuentes no existe o tiene un formato inválido."""


def parsear_fuentes(texto_yaml: str) -> list[Fuente]:
    try:
        datos = yaml.safe_load(texto_yaml)
    except yaml.YAMLError as e:
        raise ErrorConfig(f"YAML inválido: {e}") from e

    try:
        fuentes = _adaptador.validate_python(datos)
    except ValidationError as e:
        raise ErrorConfig(f"fuentes.yaml no cumple el formato esperado:\n{e}") from e

    nombres = [f.nombre for f in fuentes]
    repetidos = {n for n in nombres if nombres.count(n) > 1}
    if repetidos:
        raise ErrorConfig(f"Nombres de fuente repetidos: {sorted(repetidos)}")
    return fuentes


def cargar_fuentes(ruta: Path, *, solo_activas: bool = True) -> list[Fuente]:
    try:
        texto = ruta.read_text(encoding="utf-8")
    except OSError as e:
        raise ErrorConfig(f"No se pudo leer {ruta}: {e}") from e

    fuentes = parsear_fuentes(texto)
    return [f for f in fuentes if f.activa] if solo_activas else fuentes
