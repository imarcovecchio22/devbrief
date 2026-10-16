"""Fixtures compartidos. Los de base de datos solo corren contra TEST_DATABASE_URL."""

from collections.abc import Iterator
from urllib.parse import urlsplit

import pytest

from diario.repositorio import Repositorio
from diario.settings import RAIZ_REPO, Settings

MIGRACIONES = RAIZ_REPO / "web" / "prisma" / "migrations"
TABLAS = "items, item_fuentes, diarios, corridas"


@pytest.fixture(scope="session")
def _repo_sesion() -> Iterator[Repositorio]:
    """Una sola conexión para toda la sesión: abrirla cuesta más que los tests."""
    settings = Settings()
    url = settings.test_database_url
    if not url:
        pytest.skip("TEST_DATABASE_URL no configurada: se saltean los tests de integración")

    # Estos tests vacían las tablas: nunca contra la base principal.
    if settings.database_url and urlsplit(url).hostname == urlsplit(settings.database_url).hostname:
        pytest.fail("TEST_DATABASE_URL apunta al mismo host que DATABASE_URL. Me niego.")

    with Repositorio.conectar(url) as repo:
        _verificar_migraciones(repo)
        yield repo


def _verificar_migraciones(repo: Repositorio) -> None:
    """Falla con instrucciones si al branch de test le faltan migraciones."""
    esperadas = {d.name for d in MIGRACIONES.iterdir() if d.is_dir()}
    aplicadas = {
        fila[0]
        for fila in repo._db.execute(
            "SELECT migration_name FROM _prisma_migrations WHERE finished_at IS NOT NULL"
        )
    }
    faltan = sorted(esperadas - aplicadas)
    if faltan:
        pytest.fail(
            f"Al branch de test le faltan migraciones {faltan}: cd web && npm run db:deploy:test"
        )


@pytest.fixture
def repo(_repo_sesion: Repositorio) -> Repositorio:
    """Un repositorio sobre tablas vacías."""
    _repo_sesion._db.execute(f"TRUNCATE {TABLAS} RESTART IDENTITY CASCADE")
    return _repo_sesion
