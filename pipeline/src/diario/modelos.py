"""Tipos del dominio que circulan entre las etapas del pipeline."""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class ItemCrudo:
    """Un item tal como lo trae una fuente, ya en texto plano pero sin deduplicar."""

    fuente: str  # `nombre` de la fuente en fuentes.yaml
    area: str
    url: str  # URL original; la canónica se calcula después
    titulo: str
    contenido: str  # texto plano completo; se recorta antes de guardarlo
    fecha_publicacion: datetime | None  # siempre con zona horaria (UTC)
    senal: int | None = None  # popularidad en la fuente: puntos de HN, etc.
