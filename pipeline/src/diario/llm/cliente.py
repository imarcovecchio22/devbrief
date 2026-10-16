"""Wrapper mínimo sobre la SDK de Anthropic: pedir JSON y contar tokens."""

import logging
from dataclasses import dataclass
from typing import Any, Literal, Protocol

import anthropic
from anthropic.types import OutputConfigParam, TextBlockParam

logger = logging.getLogger(__name__)

# USD por millón de tokens (entrada, salida). Verificado en la documentación
# de Anthropic el 2026-10-16. Solo se usa para loguear un costo estimado.
PRECIOS: dict[str, tuple[float, float]] = {
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-sonnet-5-5": (2.00, 10.00),
}
FACTOR_CACHE_LECTURA = 0.1
FACTOR_CACHE_ESCRITURA = 1.25  # TTL de 5 minutos

type Effort = Literal["low", "medium", "high", "xhigh", "max"]


@dataclass(slots=True)
class ConsumoTokens:
    entrada: int = 0  # sin caché
    cache_escritura: int = 0
    cache_lectura: int = 0
    salida: int = 0
    llamadas: int = 0

    @property
    def entrada_total(self) -> int:
        return self.entrada + self.cache_escritura + self.cache_lectura

    def __iadd__(self, otro: "ConsumoTokens") -> "ConsumoTokens":
        self.entrada += otro.entrada
        self.cache_escritura += otro.cache_escritura
        self.cache_lectura += otro.cache_lectura
        self.salida += otro.salida
        self.llamadas += otro.llamadas
        return self

    def costo_usd(self, modelo: str) -> float | None:
        if modelo not in PRECIOS:
            return None
        precio_entrada, precio_salida = PRECIOS[modelo]
        tokens_entrada_equivalentes = (
            self.entrada
            + self.cache_escritura * FACTOR_CACHE_ESCRITURA
            + self.cache_lectura * FACTOR_CACHE_LECTURA
        )
        return (tokens_entrada_equivalentes * precio_entrada + self.salida * precio_salida) / 1e6

    def resumen(self, modelo: str, *, por_suscripcion: bool = False) -> str:
        costo = self.costo_usd(modelo)
        if costo is None:
            detalle_costo = ""
        elif por_suscripcion:
            # No se paga: es lo que costaría por API, como referencia de consumo.
            detalle_costo = f", equivalente API ~US$ {costo:.4f} (cubierto por la suscripción)"
        else:
            detalle_costo = f", ~US$ {costo:.4f}"
        return (
            f"{self.llamadas} llamadas a {modelo}: {self.entrada_total:,} tokens de entrada "
            f"({self.cache_lectura:,} desde caché), {self.salida:,} de salida{detalle_costo}"
        )


class ErrorLLMFatal(Exception):
    """Error que se va a repetir en todas las llamadas (credenciales, modelo, request)."""


class ErrorLLMTransitorio(Exception):
    """Error de la API o de red que puede andar en otro intento (la SDK ya reintentó)."""


@dataclass(frozen=True, slots=True)
class RespuestaLLM:
    texto: str  # "" si el modelo no devolvió texto
    stop_reason: str | None
    consumo: ConsumoTokens


class ClienteLLM(Protocol):
    """Lo que el pipeline necesita del LLM. En los tests se reemplaza por un falso."""

    def pedir_json(
        self,
        *,
        modelo: str,
        system: str,
        mensaje: str,
        schema: dict[str, Any],
        max_tokens: int,
        effort: Effort,
    ) -> RespuestaLLM: ...


class ClienteAnthropic:
    def __init__(self, api_key: str) -> None:
        self._client = anthropic.Anthropic(api_key=api_key)

    def pedir_json(
        self,
        *,
        modelo: str,
        system: str,
        mensaje: str,
        schema: dict[str, Any],
        max_tokens: int,
        effort: Effort,
    ) -> RespuestaLLM:
        # El system prompt (perfil + instrucciones) es igual en todas las
        # llamadas: lo cacheamos y las siguientes lo leen a 0.1x.
        system_cacheado: list[TextBlockParam] = [
            {"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}
        ]
        config: OutputConfigParam = {
            "effort": effort,
            "format": {"type": "json_schema", "schema": schema},
        }
        try:
            respuesta = self._client.messages.create(
                model=modelo,
                max_tokens=max_tokens,
                system=system_cacheado,
                messages=[{"role": "user", "content": mensaje}],
                output_config=config,
            )
        except anthropic.APIStatusError as e:
            # La SDK ya reintentó 429 y 5xx; lo demás (401, 403, 404, 400) es fatal.
            if e.status_code == 429 or e.status_code >= 500:
                raise ErrorLLMTransitorio(f"{e.status_code}: {e.message}") from e
            raise ErrorLLMFatal(f"{e.status_code}: {e.message}") from e
        except anthropic.APIConnectionError as e:  # incluye timeouts
            raise ErrorLLMTransitorio(str(e)) from e

        uso = respuesta.usage
        consumo = ConsumoTokens(
            entrada=uso.input_tokens,
            cache_escritura=uso.cache_creation_input_tokens or 0,
            cache_lectura=uso.cache_read_input_tokens or 0,
            salida=uso.output_tokens,
            llamadas=1,
        )
        # Con thinking activo la respuesta puede empezar con bloques `thinking`:
        # buscamos el bloque de texto por tipo, no por posición.
        texto = next((b.text for b in respuesta.content if b.type == "text"), "")
        if respuesta.stop_reason == "refusal":
            logger.warning("El modelo se negó (request %s)", respuesta._request_id)
        return RespuestaLLM(texto=texto, stop_reason=respuesta.stop_reason, consumo=consumo)
