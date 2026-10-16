"""Punto de entrada de la línea de comandos: `uv run diario <comando>`."""

import io
import logging
import sys
from datetime import UTC, datetime, timedelta

import typer

from diario import pipeline
from diario.config import ErrorConfig, Fuente, cargar_fuentes
from diario.diagnostico import Estado, probar_fuentes
from diario.fuentes import crear_cliente
from diario.repositorio import Repositorio
from diario.settings import Settings

app = typer.Typer(help="Diario técnico personal.", no_args_is_help=True)

_COLORES = {
    Estado.OK: typer.colors.GREEN,
    Estado.VACIA: typer.colors.YELLOW,
    Estado.FALLA: typer.colors.RED,
    Estado.SIN_FETCHER: typer.colors.BRIGHT_BLACK,
}


def _cargar(settings: Settings, *, solo_activas: bool) -> list[Fuente]:
    try:
        return cargar_fuentes(settings.ruta_fuentes, solo_activas=solo_activas)
    except ErrorConfig as e:
        typer.secho(str(e), fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from e


def _requerir(valor: str | None, variable: str) -> str:
    if not valor:
        typer.secho(f"Falta la variable de entorno {variable} (ver .env.example).", fg="red")
        raise typer.Exit(1)
    return valor


@app.command()
def ingestar(
    dias: int | None = typer.Option(None, help="Ventana en días (default: VENTANA_DIAS)."),
) -> None:
    """Trae las fuentes activas, deduplica y guarda los items nuevos."""
    settings = Settings()
    url = _requerir(settings.database_url, "DATABASE_URL")
    fuentes_activas = _cargar(settings, solo_activas=True)
    desde = datetime.now(UTC) - timedelta(days=dias or settings.ventana_dias)

    with Repositorio.conectar(url) as repo, crear_cliente() as cliente:
        corrida = repo.iniciar_corrida()
        try:
            resumen = pipeline.ingestar(
                repo,
                fuentes_activas,
                cliente,
                desde=desde,
                dias_dedupe=settings.dias_dedupe,
                max_contenido=settings.max_caracteres_contenido,
            )
        except Exception as e:
            repo.cerrar_corrida(corrida, errores=[{"etapa": "ingesta", "error": repr(e)}])
            raise
        repo.cerrar_corrida(corrida, items_nuevos=resumen.items_nuevos, errores=resumen.errores)

    typer.echo(
        f"{resumen.items_traidos} items traídos -> {resumen.grupos} noticias -> "
        f"{resumen.items_nuevos} nuevas, {resumen.apariciones_nuevas} apariciones nuevas."
    )
    for error in resumen.errores:
        typer.secho(f"  falló {error['fuente']}: {error['error']}", fg=typer.colors.YELLOW)


@app.command()
def fuentes(todas: bool = typer.Option(False, "--todas", help="Incluir las inactivas.")) -> None:
    """Lista las fuentes configuradas."""
    for f in _cargar(Settings(), solo_activas=not todas):
        marca = "✔" if f.activa else "·"
        typer.echo(f"{marca} {f.nombre:<28} {f.tipo:<16} {f.area}")


@app.command("probar-fuentes")
def probar_fuentes_cmd(
    solo_activas: bool = typer.Option(False, "--solo-activas", help="No probar las inactivas."),
    dias: int | None = typer.Option(None, help="Ventana en días (default: VENTANA_DIAS)."),
) -> None:
    """Prueba cada fuente e informa cuáles fallan. Sale con código 1 si alguna falla."""
    settings = Settings()
    lista = _cargar(settings, solo_activas=solo_activas)
    desde = datetime.now(UTC) - timedelta(days=dias or settings.ventana_dias)

    with crear_cliente() as cliente:
        resultados = probar_fuentes(lista, cliente, desde)

    for r in resultados:
        marca = "✔" if r.fuente.activa else "·"
        estado = typer.style(f"{r.estado:<11}", fg=_COLORES[r.estado])
        tiempo = f"{r.segundos:4.1f}s" if r.segundos else "     "
        cantidad = f"{r.cantidad:>3} items"
        typer.echo(f"{marca} {estado} {r.fuente.nombre:<24} {cantidad} {tiempo}  {r.detalle[:70]}")

    fallas = [r for r in resultados if r.estado is Estado.FALLA]
    resumen = f"\n{len(resultados)} fuentes probadas, {len(fallas)} con falla."
    typer.secho(resumen, fg=typer.colors.RED if fallas else typer.colors.GREEN)
    if fallas:
        raise typer.Exit(1)


@app.callback()
def _main(verbose: bool = typer.Option(False, "--verbose", "-v", help="Logs de debug.")) -> None:
    # En Windows, stdout redirigido usa cp1252 y rompe con emojis o símbolos
    # en los títulos de las noticias. Forzamos UTF-8.
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(encoding="utf-8")

    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    # httpx loguea cada request en INFO: demasiado ruido salvo en modo verbose.
    logging.getLogger("httpx").setLevel(logging.DEBUG if verbose else logging.WARNING)
