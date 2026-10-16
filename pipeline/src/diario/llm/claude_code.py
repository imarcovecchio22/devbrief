"""Backend LLM que usa la CLI de Claude Code en modo no interactivo (`claude -p`).

Consume el cupo de la suscripción de Claude en vez de créditos de la API.
En CI se autentica con CLAUDE_CODE_OAUTH_TOKEN (generado con `claude setup-token`).
"""

import json
import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from diario.llm.cliente import (
    ConsumoTokens,
    Effort,
    ErrorLLMFatal,
    ErrorLLMTransitorio,
    RespuestaLLM,
)

logger = logging.getLogger(__name__)

# Si cualquiera de estas está en el entorno, Claude Code factura por la API
# en lugar de usar la suscripción: se las sacamos al subproceso.
_VARIABLES_DE_API = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")


class ClienteClaudeCode:
    def __init__(self, ejecutable: str = "claude", *, timeout_segundos: float = 600) -> None:
        self._ejecutable = ejecutable
        self._timeout = timeout_segundos

    def pedir_json(
        self,
        *,
        modelo: str,
        system: str,
        mensaje: str,
        schema: dict[str, Any],
        max_tokens: int,  # la CLI no lo expone; se ignora
        effort: Effort,
    ) -> RespuestaLLM:
        ruta = shutil.which(self._ejecutable)
        if ruta is None:
            raise ErrorLLMFatal(f"No se encontró el ejecutable {self._ejecutable!r} de Claude Code")

        # Carpeta vacía como directorio de trabajo: así no carga el CLAUDE.md del
        # repo ni ninguna otra configuración de proyecto.
        with tempfile.TemporaryDirectory(prefix="diario-") as carpeta:
            archivo_system = Path(carpeta) / "system.md"
            archivo_system.write_text(system, encoding="utf-8")
            comando = [
                ruta,
                "--print",
                "--model", modelo,
                "--effort", effort,
                "--output-format", "json",
                "--json-schema", json.dumps(schema),
                "--system-prompt-file", str(archivo_system),
                "--tools", "",  # sin herramientas: solo responde
                "--setting-sources", "",  # sin settings, hooks ni plugins del usuario
                "--strict-mcp-config",  # sin servidores MCP
                "--no-session-persistence",
            ]  # fmt: skip
            entorno = {k: v for k, v in os.environ.items() if k not in _VARIABLES_DE_API}
            try:
                proceso = subprocess.run(
                    comando,
                    # El mensaje va por stdin: en Windows la línea de comandos tiene
                    # un límite de ~32K caracteres y un lote de noticias lo supera.
                    input=mensaje,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    cwd=carpeta,
                    env=entorno,
                    timeout=self._timeout,
                    check=False,
                )
            except subprocess.TimeoutExpired as e:
                raise ErrorLLMTransitorio(f"claude -p tardó más de {self._timeout:.0f}s") from e

        return _interpretar(proceso)


def _interpretar(proceso: subprocess.CompletedProcess[str]) -> RespuestaLLM:
    try:
        salida = json.loads(proceso.stdout)
    except json.JSONDecodeError:
        detalle = (proceso.stderr or proceso.stdout).strip()[:300]
        if any(p in detalle.lower() for p in ("login", "log in", "auth", "token")):
            raise ErrorLLMFatal(f"Claude Code no está autenticado: {detalle}") from None
        raise ErrorLLMTransitorio(
            f"claude -p salió con código {proceso.returncode}: {detalle}"
        ) from None

    if salida.get("is_error"):
        estado = salida.get("api_error_status")
        mensaje = str(salida.get("result") or salida.get("subtype"))
        texto = mensaje.lower()
        if estado in (401, 403) or "auth" in texto or "login" in texto:
            raise ErrorLLMFatal(f"Claude Code no está autenticado: {mensaje}")
        if estado == 429 or "limit" in texto:
            # Cupo del plan agotado: seguir solo repetiría el error. Se corta y
            # los items quedan pendientes, sin gastar intentos.
            raise ErrorLLMFatal(f"Se agotó el cupo de la suscripción: {mensaje}")
        raise ErrorLLMTransitorio(f"Error de Claude Code ({estado}): {mensaje}")

    estructurada = salida.get("structured_output")
    texto_respuesta = (
        json.dumps(estructurada, ensure_ascii=False)
        if estructurada is not None
        else str(salida.get("result") or "")
    )
    uso = salida.get("usage") or {}
    consumo = ConsumoTokens(
        entrada=int(uso.get("input_tokens") or 0),
        cache_escritura=int(uso.get("cache_creation_input_tokens") or 0),
        cache_lectura=int(uso.get("cache_read_input_tokens") or 0),
        salida=int(uso.get("output_tokens") or 0),
        llamadas=1,
    )
    # Con --json-schema el stop_reason es "tool_use" (la salida estructurada es
    # una herramienta interna); lo normalizamos para que no parezca un corte.
    stop = salida.get("stop_reason")
    return RespuestaLLM(
        texto=texto_respuesta,
        stop_reason="end_turn" if stop == "tool_use" else stop,
        consumo=consumo,
    )
