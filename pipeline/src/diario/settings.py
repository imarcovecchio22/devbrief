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
    # Solo para los tests de integración: un branch de Neon aparte.
    test_database_url: str | None = None

    config_dir: Path = RAIZ_REPO / "config"
    # Items publicados hace más días que esto se descartan en la ingesta.
    ventana_dias: int = 3
    # Días hacia atrás contra los que se deduplica por título.
    dias_dedupe: int = 7
    # Texto que se guarda por item (y se manda al LLM): ~500 tokens.
    max_caracteres_contenido: int = 2000

    # Modelos (IDs verificados en la documentación de Anthropic el 2026-10-16).
    modelo_puntaje: str = "claude-haiku-5-5"
    modelo_redaccion: str = "claude-sonnet-5-5"
    # Respuestas inválidas antes de dejar de reintentar un item.
    max_intentos_puntaje: int = 2
    # Tope de items a puntuar por corrida: protege el costo si algo se desborda.
    max_items_puntaje: int = 300
    # Llamadas en paralelo al LLM.
    hilos_llm: int = 4

    @property
    def ruta_fuentes(self) -> Path:
        return self.config_dir / "fuentes.yaml"

    @property
    def ruta_perfil(self) -> Path:
        return self.config_dir / "perfil.md"
