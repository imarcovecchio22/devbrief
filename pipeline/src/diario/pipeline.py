"""Orquestación de las etapas del pipeline."""

import logging
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx

from diario.config import Fuente
from diario.dedupe import agrupar
from diario.fuentes import ErrorFuente, traer_items
from diario.fuentes.articulos import descargar_textos
from diario.llm.cliente import (
    ClienteLLM,
    ConsumoTokens,
    Effort,
    ErrorLLMFatal,
    ErrorLLMTransitorio,
    RespuestaLLM,
)
from diario.llm.puntaje import (
    SCHEMA_LOTE,
    ItemAPuntuar,
    armar_mensaje_lote,
    armar_system,
    parsear_lote,
)
from diario.llm.redaccion import (
    SCHEMA_DIARIO,
    UMBRAL_RELLENO,
    parsear_diario,
)
from diario.llm.redaccion import armar_mensaje as armar_mensaje_redaccion
from diario.llm.redaccion import armar_system as armar_system_redaccion
from diario.llm.respuesta import ErrorRespuestaLLM
from diario.modelos import ItemCrudo
from diario.repositorio import Repositorio
from diario.settings import Settings

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ResumenIngesta:
    items_traidos: int = 0
    grupos: int = 0
    items_nuevos: int = 0
    apariciones_nuevas: int = 0
    errores: list[dict[str, str]] = field(default_factory=list)


def traer_todas(
    fuentes: Sequence[Fuente], cliente: httpx.Client, desde: datetime
) -> tuple[list[ItemCrudo], list[dict[str, str]]]:
    """Trae todas las fuentes en paralelo. Una fuente que falla no corta las demás."""

    def traer_una(fuente: Fuente) -> list[ItemCrudo] | dict[str, str]:
        try:
            items = traer_items(fuente, cliente, desde)
        except (httpx.HTTPError, ErrorFuente) as e:
            logger.warning("Fuente %s falló: %s", fuente.nombre, e)
            return {"fuente": fuente.nombre, "error": f"{type(e).__name__}: {e}"}
        except Exception as e:
            # Un bug en un parser: lo registramos con traceback y seguimos.
            logger.exception("Error inesperado en la fuente %s", fuente.nombre)
            return {"fuente": fuente.nombre, "error": f"{type(e).__name__}: {e}"}
        logger.info("%-24s %3d items", fuente.nombre, len(items))
        return items

    items: list[ItemCrudo] = []
    errores: list[dict[str, str]] = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        for resultado in pool.map(traer_una, fuentes):
            if isinstance(resultado, dict):
                errores.append(resultado)
            else:
                items.extend(resultado)
    return items, errores


@dataclass(slots=True)
class ResumenPuntaje:
    puntuados: int = 0
    aprobados: int = 0  # puntaje >= UMBRAL_DIARIO
    invalidos: int = 0  # respuesta que no se pudo usar: gasta un intento del item
    fallidos: int = 0  # error transitorio del LLM: se reintenta en otra corrida
    consumo: ConsumoTokens = field(default_factory=ConsumoTokens)


UMBRAL_DIARIO = 7
# Con lotes de ~20 la respuesta ronda los 4K tokens; el thinking también cuenta.
_MAX_TOKENS_PUNTAJE = 16000
_EFFORT_PUNTAJE: Effort = "low"  # clasificación: no necesita pensar mucho


def puntuar(
    repo: Repositorio,
    llm: ClienteLLM,
    items: Sequence[ItemAPuntuar],
    *,
    perfil: str,
    modelo: str,
    tamano_lote: int,
    hilos: int,
) -> ResumenPuntaje:
    """Puntúa los items de a lotes y guarda cada lote apenas llega.

    Guardar a medida que llegan hace que un corte a mitad de camino no tire
    tokens ya gastados: la próxima corrida sigue con los que faltan.
    """
    resumen = ResumenPuntaje()
    if not items:
        return resumen
    system = armar_system(perfil)
    lotes = [items[i : i + tamano_lote] for i in range(0, len(items), tamano_lote)]

    def llamar(lote: Sequence[ItemAPuntuar]) -> RespuestaLLM | ErrorLLMTransitorio:
        try:
            return llm.pedir_json(
                modelo=modelo,
                system=system,
                mensaje=armar_mensaje_lote(lote),
                schema=SCHEMA_LOTE,
                max_tokens=_MAX_TOKENS_PUNTAJE,
                effort=_EFFORT_PUNTAJE,
            )
        except ErrorLLMTransitorio as e:
            return e  # ErrorLLMFatal sí se propaga y corta todo

    def fallar(item: ItemAPuntuar, motivo: str) -> None:
        logger.warning("Item %d sin puntaje: %s", item.id, motivo)
        repo.registrar_intento_fallido(item.id)
        resumen.invalidos += 1

    def procesar(
        lote: Sequence[ItemAPuntuar], resultado: RespuestaLLM | ErrorLLMTransitorio
    ) -> None:
        if isinstance(resultado, ErrorLLMTransitorio):
            logger.warning("Lote de %d items sin puntuar por error: %s", len(lote), resultado)
            resumen.fallidos += len(lote)
            return

        resumen.consumo += resultado.consumo
        try:
            if resultado.stop_reason in ("refusal", "max_tokens"):
                raise ErrorRespuestaLLM(f"stop_reason={resultado.stop_reason}")
            puntajes = parsear_lote(resultado.texto, {i.id: i.area for i in lote})
        except ErrorRespuestaLLM as e:
            for item in lote:
                fallar(item, f"respuesta inválida del lote ({e})")
            return

        for item in lote:
            p = puntajes.get(item.id)
            if p is None:
                fallar(item, "el modelo no lo evaluó")
                continue
            repo.guardar_puntaje(item.id, p.puntaje, p.seccion, p.motivo)
            resumen.puntuados += 1
            resumen.aprobados += p.puntaje >= UMBRAL_DIARIO
            logger.debug("%2d %-10s %s", p.puntaje, p.seccion, item.titulo)

    # El primer lote va solo: escribe el system prompt en caché y los demás lo
    # leen. Si salieran todos juntos, todos pagarían la escritura completa.
    primero, *resto = lotes
    procesar(primero, llamar(primero))

    with ThreadPoolExecutor(max_workers=hilos) as pool:
        futuros = {pool.submit(llamar, lote): lote for lote in resto}
        try:
            for futuro in as_completed(futuros):
                procesar(futuros[futuro], futuro.result())
        except BaseException:
            # Error fatal (o Ctrl+C): no seguir gastando en las llamadas pendientes.
            pool.shutdown(wait=False, cancel_futures=True)
            raise

    logger.info(
        "Puntaje: %d puntuados (%d con %d o más), %d inválidos, %d con error. %s",
        resumen.puntuados,
        resumen.aprobados,
        UMBRAL_DIARIO,
        resumen.invalidos,
        resumen.fallidos,
        resumen.consumo.resumen(modelo),
    )
    return resumen


@dataclass(frozen=True, slots=True)
class ResumenContenido:
    pendientes: int
    completados: int


def completar_contenido(
    repo: Repositorio, cliente: httpx.Client, *, max_contenido: int
) -> ResumenContenido:
    """Baja el artículo de los items que llegaron sin texto (la mayoría de HN).

    Solo toca items sin puntuar: como el puntaje se calcula en la misma
    corrida, un sitio que bloquea la descarga se intenta una sola vez.
    """
    pendientes = repo.items_sin_contenido()
    if not pendientes:
        return ResumenContenido(pendientes=0, completados=0)

    textos = descargar_textos(cliente, [url for _, url in pendientes])
    completados = repo.actualizar_contenidos(
        [(item_id, texto) for (item_id, _), texto in zip(pendientes, textos, strict=True)],
        max_contenido,
    )
    logger.info("Contenido: %d de %d items sin texto completados", completados, len(pendientes))
    return ResumenContenido(pendientes=len(pendientes), completados=completados)


def ingestar(
    repo: Repositorio,
    fuentes: Sequence[Fuente],
    cliente: httpx.Client,
    *,
    desde: datetime,
    dias_dedupe: int,
    max_contenido: int,
) -> ResumenIngesta:
    items, errores = traer_todas(fuentes, cliente, desde)
    existentes = repo.referencias_recientes(dias_dedupe)
    grupos = agrupar(items, existentes)
    guardado = repo.guardar_grupos(grupos, max_contenido)

    resumen = ResumenIngesta(
        items_traidos=len(items),
        grupos=len(grupos),
        items_nuevos=guardado.items_nuevos,
        apariciones_nuevas=guardado.apariciones_nuevas,
        errores=errores,
    )
    logger.info(
        "Ingesta: %d items -> %d grupos -> %d nuevos (%d apariciones nuevas), %d fuentes con error",
        resumen.items_traidos,
        resumen.grupos,
        resumen.items_nuevos,
        resumen.apariciones_nuevas,
        len(errores),
    )
    return resumen


# ---------- redacción ----------

ZONA_HORARIA = ZoneInfo("America/Argentina/Buenos_Aires")
_MAX_TOKENS_REDACCION = 16000
_EFFORT_REDACCION: Effort = "high"  # una llamada por día: que escriba bien


def hoy_argentina() -> date:
    return datetime.now(ZONA_HORARIA).date()


@dataclass(slots=True)
class ResumenRedaccion:
    fecha: date
    diario_id: int | None = None
    candidatos: int = 0
    notas: int = 0
    radar: int = 0
    salteado: str | None = None  # motivo, si no se generó
    consumo: ConsumoTokens = field(default_factory=ConsumoTokens)


def redactar(
    repo: Repositorio,
    llm: ClienteLLM,
    *,
    perfil: str,
    modelo: str,
    fecha: date,
    dias: int,
    forzar: bool = False,
) -> ResumenRedaccion:
    """Escribe y guarda el diario de `fecha`. Si ya existe, no hace nada (salvo `forzar`)."""
    resumen = ResumenRedaccion(fecha=fecha)
    if repo.diario_existe(fecha) and not forzar:
        resumen.salteado = "ya existe el diario de esa fecha; usá --forzar para regenerarlo"
        return resumen

    candidatos = repo.candidatos_diario(dias=dias, fecha=fecha)
    resumen.candidatos = len(candidatos)
    if not any(c.puntaje >= UMBRAL_RELLENO for c in candidatos):
        resumen.salteado = f"no hay noticias con puntaje {UMBRAL_RELLENO} o más"
        return resumen

    respuesta = llm.pedir_json(
        modelo=modelo,
        system=armar_system_redaccion(perfil),
        mensaje=armar_mensaje_redaccion(candidatos, fecha),
        schema=SCHEMA_DIARIO,
        max_tokens=_MAX_TOKENS_REDACCION,
        effort=_EFFORT_REDACCION,
    )
    resumen.consumo += respuesta.consumo
    if respuesta.stop_reason in ("refusal", "max_tokens"):
        raise ErrorRespuestaLLM(f"La redacción terminó con stop_reason={respuesta.stop_reason}")

    diario = parsear_diario(respuesta.texto, {c.item_id: c for c in candidatos}, fecha)
    resumen.diario_id = repo.guardar_diario(diario)
    resumen.notas = diario.cantidad_notas
    resumen.radar = len(diario.radar)
    logger.info(
        "Diario %s: %d notas y %d en el radar, de %d candidatas. %s",
        fecha,
        resumen.notas,
        resumen.radar,
        resumen.candidatos,
        resumen.consumo.resumen(modelo),
    )
    return resumen


# ---------- corrida completa ----------


@dataclass(slots=True)
class ResumenCorrida:
    ingesta: ResumenIngesta | None = None
    contenido: ResumenContenido | None = None
    puntaje: ResumenPuntaje | None = None
    redaccion: ResumenRedaccion | None = None
    errores: list[dict[str, str]] = field(default_factory=list)
    fallo: bool = False  # alguna etapa no pudo completarse

    @property
    def consumo(self) -> ConsumoTokens:
        total = ConsumoTokens()
        if self.puntaje:
            total += self.puntaje.consumo
        if self.redaccion:
            total += self.redaccion.consumo
        return total


def correr_todo(
    repo: Repositorio,
    cliente: httpx.Client,
    llm: ClienteLLM,
    fuentes: Sequence[Fuente],
    *,
    settings: Settings,
    perfil: str,
    fecha: date,
    forzar: bool = False,
) -> ResumenCorrida:
    """Ingesta -> contenido -> puntaje -> redacción.

    Las fuentes que fallan se registran y no cortan nada. Un error del LLM en
    el puntaje o la redacción corta la corrida y la marca como fallida; lo ya
    guardado queda guardado, así que la próxima corrida retoma desde ahí.
    """
    r = ResumenCorrida()

    desde = datetime.now(UTC) - timedelta(days=settings.ventana_dias)
    r.ingesta = ingestar(
        repo,
        fuentes,
        cliente,
        desde=desde,
        dias_dedupe=settings.dias_dedupe,
        max_contenido=settings.max_caracteres_contenido,
    )
    r.errores.extend(r.ingesta.errores)

    r.contenido = completar_contenido(
        repo, cliente, max_contenido=settings.max_caracteres_contenido
    )

    areas = {f.nombre: f.area for f in fuentes}
    items = repo.items_para_puntuar(
        max_intentos=settings.max_intentos_puntaje,
        limite=settings.max_items_puntaje,
        areas=areas,
    )
    try:
        r.puntaje = puntuar(
            repo,
            llm,
            items,
            perfil=perfil,
            modelo=settings.modelo_puntaje,
            tamano_lote=settings.tamano_lote_puntaje,
            hilos=settings.hilos_llm,
        )
    except ErrorLLMFatal as e:
        logger.error("Puntaje cortado: %s", e)
        r.errores.append({"etapa": "puntaje", "error": str(e)})
        r.fallo = True
        return r

    try:
        r.redaccion = redactar(
            repo,
            llm,
            perfil=perfil,
            modelo=settings.modelo_redaccion,
            fecha=fecha,
            dias=settings.ventana_dias,
            forzar=forzar,
        )
    except (ErrorLLMFatal, ErrorLLMTransitorio, ErrorRespuestaLLM) as e:
        logger.error("Redacción fallida: %s", e)
        r.errores.append({"etapa": "redaccion", "error": str(e)})
        r.fallo = True
    return r
