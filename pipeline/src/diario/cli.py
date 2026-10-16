"""Punto de entrada de la línea de comandos: `uv run diario <comando>`."""

import io
import logging
import sys
from datetime import UTC, date, datetime, timedelta

import typer

from diario import pipeline
from diario.config import ErrorConfig, Fuente, cargar_fuentes
from diario.diagnostico import Estado, probar_fuentes
from diario.fuentes import crear_cliente
from diario.llm.claude_code import ClienteClaudeCode
from diario.llm.cliente import (
    ClienteAnthropic,
    ClienteLLM,
    ErrorLLMFatal,
    ErrorLLMTransitorio,
)
from diario.llm.respuesta import ErrorRespuestaLLM
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
def run(
    forzar: bool = typer.Option(False, "--forzar", help="Regenerar el diario de hoy si ya existe."),
) -> None:
    """Corrida diaria completa: ingesta, contenido, puntaje y redacción."""
    settings = Settings()
    url = _requerir(settings.database_url, "DATABASE_URL")
    llm = _crear_llm(settings)
    fuentes_activas = _cargar(settings, solo_activas=True)
    perfil = settings.ruta_perfil.read_text(encoding="utf-8")
    hoy = pipeline.hoy_argentina()

    with Repositorio.conectar(url) as repo, crear_cliente() as cliente:
        corrida = repo.iniciar_corrida()
        resumen = pipeline.ResumenCorrida()
        try:
            resumen = pipeline.correr_todo(
                repo,
                cliente,
                llm,
                fuentes_activas,
                settings=settings,
                perfil=perfil,
                fecha=hoy,
                forzar=forzar,
            )
        except Exception as e:
            # Algo inesperado (ej. se cayó la base): se registra y se propaga.
            resumen.errores.append({"etapa": "corrida", "error": repr(e)})
            resumen.fallo = True
            raise
        finally:
            consumo = resumen.consumo
            repo.cerrar_corrida(
                corrida,
                items_nuevos=resumen.ingesta.items_nuevos if resumen.ingesta else 0,
                items_puntuados=resumen.puntaje.puntuados if resumen.puntaje else 0,
                tokens_entrada=consumo.entrada_total,
                tokens_salida=consumo.salida,
                errores=resumen.errores,
            )

    _imprimir_resumen(resumen, settings, hoy)
    if resumen.fallo:
        raise typer.Exit(1)


def _imprimir_resumen(resumen: pipeline.ResumenCorrida, settings: Settings, hoy: date) -> None:
    por_suscripcion = settings.llm_backend == "claude-code"
    if resumen.ingesta:
        i = resumen.ingesta
        typer.echo(f"Ingesta:   {i.items_traidos} items -> {i.items_nuevos} noticias nuevas")
    if resumen.contenido:
        c = resumen.contenido
        typer.echo(f"Contenido: {c.completados} de {c.pendientes} artículos sin texto completados")
    if resumen.puntaje:
        p = resumen.puntaje
        typer.echo(f"Puntaje:   {p.puntuados} puntuados, {p.aprobados} con 7+")
        consumo = p.consumo.resumen(settings.modelo_puntaje, por_suscripcion=por_suscripcion)
        typer.echo(f"           {consumo}")
    if resumen.redaccion:
        r = resumen.redaccion
        if r.salteado:
            typer.echo(f"Diario:    {hoy}: no se generó ({r.salteado})")
        else:
            typer.echo(f"Diario:    {hoy}: {r.notas} notas y {r.radar} en el radar")
            consumo = r.consumo.resumen(settings.modelo_redaccion, por_suscripcion=por_suscripcion)
            typer.echo(f"           {consumo}")
    for error in resumen.errores:
        origen = error.get("fuente") or error.get("etapa")
        color = typer.colors.RED if "etapa" in error else typer.colors.YELLOW
        typer.secho(f"  error en {origen}: {error['error']}", fg=color)


def _crear_llm(settings: Settings) -> ClienteLLM:
    if settings.llm_backend == "api":
        return ClienteAnthropic(_requerir(settings.anthropic_api_key, "ANTHROPIC_API_KEY"))
    return ClienteClaudeCode(settings.claude_ejecutable)


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
def puntuar(
    limite: int | None = typer.Option(
        None, help="Máximo de items a puntuar (default: MAX_ITEMS_PUNTAJE)."
    ),
    repuntuar: bool = typer.Option(
        False,
        "--repuntuar",
        help="Volver a puntuar los items de la ventana que no salieron en un diario "
        "(después de cambiar el perfil).",
    ),
) -> None:
    """Puntúa con el LLM los items nuevos según config/perfil.md."""
    settings = Settings()
    url = _requerir(settings.database_url, "DATABASE_URL")
    llm = _crear_llm(settings)
    perfil = settings.ruta_perfil.read_text(encoding="utf-8")
    areas = {f.nombre: f.area for f in _cargar(settings, solo_activas=False)}

    with Repositorio.conectar(url) as repo:
        if repuntuar:
            reiniciados = repo.reiniciar_puntajes(settings.ventana_dias)
            typer.echo(f"{reiniciados} items vuelven a puntuarse con el perfil actual.")
        items = repo.items_para_puntuar(
            max_intentos=settings.max_intentos_puntaje,
            limite=limite or settings.max_items_puntaje,
            areas=areas,
        )
        typer.echo(
            f"{len(items)} items para puntuar con {settings.modelo_puntaje} "
            f"(backend: {settings.llm_backend})."
        )
        corrida = repo.iniciar_corrida()
        resumen = pipeline.ResumenPuntaje()
        try:
            resumen = pipeline.puntuar(
                repo,
                llm,
                items,
                perfil=perfil,
                modelo=settings.modelo_puntaje,
                tamano_lote=settings.tamano_lote_puntaje,
                hilos=settings.hilos_llm,
            )
        except ErrorLLMFatal as e:
            typer.secho(f"Error del LLM: {e}", fg=typer.colors.RED, err=True)
            raise typer.Exit(1) from e
        finally:
            repo.cerrar_corrida(
                corrida,
                items_puntuados=resumen.puntuados,
                tokens_entrada=resumen.consumo.entrada_total,
                tokens_salida=resumen.consumo.salida,
            )

    typer.echo(
        f"{resumen.puntuados} puntuados ({resumen.aprobados} con {pipeline.UMBRAL_DIARIO}+), "
        f"{resumen.invalidos} inválidos, {resumen.fallidos} con error de API."
    )
    por_suscripcion = settings.llm_backend == "claude-code"
    typer.echo(resumen.consumo.resumen(settings.modelo_puntaje, por_suscripcion=por_suscripcion))


@app.command()
def redactar(
    forzar: bool = typer.Option(False, "--forzar", help="Regenerar aunque ya exista."),
    fecha: datetime | None = typer.Option(
        None, formats=["%Y-%m-%d"], help="Fecha del diario (default: hoy en Argentina)."
    ),
) -> None:
    """Escribe el diario del día con las noticias mejor puntuadas."""
    settings = Settings()
    url = _requerir(settings.database_url, "DATABASE_URL")
    llm = _crear_llm(settings)
    perfil = settings.ruta_perfil.read_text(encoding="utf-8")
    dia = fecha.date() if fecha else pipeline.hoy_argentina()

    with Repositorio.conectar(url) as repo:
        corrida = repo.iniciar_corrida()
        resumen = pipeline.ResumenRedaccion(fecha=dia)
        try:
            resumen = pipeline.redactar(
                repo,
                llm,
                perfil=perfil,
                modelo=settings.modelo_redaccion,
                fecha=dia,
                dias=settings.ventana_dias,
                forzar=forzar,
            )
        except (ErrorLLMFatal, ErrorLLMTransitorio, ErrorRespuestaLLM) as e:
            repo.cerrar_corrida(corrida, errores=[{"etapa": "redaccion", "error": str(e)}])
            typer.secho(f"No se pudo redactar el diario: {e}", fg=typer.colors.RED, err=True)
            raise typer.Exit(1) from e
        repo.cerrar_corrida(
            corrida,
            tokens_entrada=resumen.consumo.entrada_total,
            tokens_salida=resumen.consumo.salida,
        )

    if resumen.salteado:
        typer.echo(f"Diario del {dia}: no se generó ({resumen.salteado}).")
        return
    typer.echo(
        f"Diario del {dia} guardado: {resumen.notas} notas y {resumen.radar} en el radar "
        f"(de {resumen.candidatos} candidatas)."
    )
    por_suscripcion = settings.llm_backend == "claude-code"
    typer.echo(resumen.consumo.resumen(settings.modelo_redaccion, por_suscripcion=por_suscripcion))


@app.command("completar-contenido")
def completar_contenido_cmd() -> None:
    """Baja el texto de los artículos que llegaron solo con título (ej. HN)."""
    settings = Settings()
    url = _requerir(settings.database_url, "DATABASE_URL")
    with Repositorio.conectar(url) as repo, crear_cliente() as cliente:
        resumen = pipeline.completar_contenido(
            repo, cliente, max_contenido=settings.max_caracteres_contenido
        )
    typer.echo(f"{resumen.completados} de {resumen.pendientes} items sin texto completados.")


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
