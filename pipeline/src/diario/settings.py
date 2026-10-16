"""Configuración por variables de entorno (y .env en la raíz del repo, si existe)."""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# src/diario/settings.py -> parents[3] es la raíz del repo
RAIZ_REPO = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=RAIZ_REPO / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Opcionales acá: cada comando valida que estén los que necesita.
    anthropic_api_key: str | None = None
    database_url: str | None = None

    config_dir: Path = RAIZ_REPO / "config"
    # Items publicados hace más días que esto se descartan en la ingesta.
    ventana_dias: int = 3

    @property
    def ruta_fuentes(self) -> Path:
        return self.config_dir / "fuentes.yaml"

    @property
    def ruta_perfil(self) -> Path:
        return self.config_dir / "perfil.md"
