"""Backend `claude -p`, sin ejecutar Claude Code: se reemplaza subprocess.run."""

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from diario.llm.claude_code import ClienteClaudeCode
from diario.llm.cliente import ErrorLLMFatal, ErrorLLMTransitorio

SALIDA_OK: dict[str, Any] = {
    "type": "result",
    "subtype": "success",
    "is_error": False,
    "stop_reason": "tool_use",
    "result": "{}",
    "structured_output": {"evaluaciones": [{"id": 1, "puntaje": 8}]},
    "usage": {
        "input_tokens": 10,
        "cache_creation_input_tokens": 1300,
        "cache_read_input_tokens": 0,
        "output_tokens": 400,
    },
}


class SubprocesoFalso:
    def __init__(self, stdout: str = "", returncode: int = 0, stderr: str = "") -> None:
        self.resultado = subprocess.CompletedProcess([], returncode, stdout, stderr)
        self.llamadas: list[dict[str, Any]] = []

    def __call__(self, comando: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        # El system prompt se escribe en un archivo temporal: lo leemos ahora,
        # antes de que se borre.
        archivo = Path(comando[comando.index("--system-prompt-file") + 1])
        self.llamadas.append({"comando": comando, "system": archivo.read_text("utf-8"), **kwargs})
        return self.resultado


@pytest.fixture
def ejecutable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("diario.llm.claude_code.shutil.which", lambda _: "C:/bin/claude.exe")


def _pedir(cliente: ClienteClaudeCode | None = None) -> Any:
    return (cliente or ClienteClaudeCode()).pedir_json(
        modelo="claude-haiku-5-5",
        system="Perfil",
        mensaje="Evaluá estas noticias",
        schema={"type": "object"},
        max_tokens=1000,
        effort="low",
    )


def _instalar(monkeypatch: pytest.MonkeyPatch, falso: SubprocesoFalso) -> SubprocesoFalso:
    monkeypatch.setattr("diario.llm.claude_code.subprocess.run", falso)
    return falso


@pytest.mark.usefixtures("ejecutable")
def test_respuesta_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    falso = _instalar(monkeypatch, SubprocesoFalso(json.dumps(SALIDA_OK)))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-no-usar")

    r = _pedir()

    assert json.loads(r.texto) == SALIDA_OK["structured_output"]
    assert r.stop_reason == "end_turn"  # "tool_use" se normaliza
    assert (r.consumo.entrada_total, r.consumo.salida, r.consumo.llamadas) == (1310, 400, 1)

    llamada = falso.llamadas[0]
    comando = llamada["comando"]
    # Nunca la API: sin ANTHROPIC_API_KEY en el entorno del subproceso.
    assert "ANTHROPIC_API_KEY" not in llamada["env"]
    # El mensaje va por stdin y el system prompt por archivo.
    assert llamada["input"] == "Evaluá estas noticias"
    assert llamada["system"] == "Perfil"
    assert comando[comando.index("--model") + 1] == "claude-haiku-5-5"
    assert comando[comando.index("--effort") + 1] == "low"
    assert comando[comando.index("--tools") + 1] == ""
    assert "--no-session-persistence" in comando
    # Corre en una carpeta vacía, no en el repo (no carga su CLAUDE.md).
    assert Path(llamada["cwd"]).name.startswith("diario-")


@pytest.mark.usefixtures("ejecutable")
def test_sin_salida_estructurada_usa_el_texto(monkeypatch: pytest.MonkeyPatch) -> None:
    salida = SALIDA_OK | {"structured_output": None, "result": '{"evaluaciones": []}'}
    _instalar(monkeypatch, SubprocesoFalso(json.dumps(salida)))
    assert _pedir().texto == '{"evaluaciones": []}'


@pytest.mark.parametrize(
    ("salida", "error"),
    [
        ({"is_error": True, "api_error_status": 401, "result": "Invalid token"}, ErrorLLMFatal),
        ({"is_error": True, "result": "Not logged in · Please run /login"}, ErrorLLMFatal),
        ({"is_error": True, "api_error_status": 429, "result": "Rate limited"}, ErrorLLMFatal),
        ({"is_error": True, "result": "Claude usage limit reached"}, ErrorLLMFatal),
        ({"is_error": True, "api_error_status": 529, "result": "Overloaded"}, ErrorLLMTransitorio),
    ],
    ids=["401", "sin-login", "429", "cupo", "529"],
)
@pytest.mark.usefixtures("ejecutable")
def test_errores_reportados_por_claude_code(
    monkeypatch: pytest.MonkeyPatch, salida: dict[str, Any], error: type[Exception]
) -> None:
    _instalar(monkeypatch, SubprocesoFalso(json.dumps(salida)))
    with pytest.raises(error):
        _pedir()


@pytest.mark.usefixtures("ejecutable")
def test_salida_que_no_es_json(monkeypatch: pytest.MonkeyPatch) -> None:
    _instalar(monkeypatch, SubprocesoFalso("", returncode=1, stderr="Unexpected crash"))
    with pytest.raises(ErrorLLMTransitorio, match="código 1"):
        _pedir()

    _instalar(monkeypatch, SubprocesoFalso("", returncode=1, stderr="Please log in first"))
    with pytest.raises(ErrorLLMFatal):
        _pedir()


@pytest.mark.usefixtures("ejecutable")
def test_timeout_es_transitorio(monkeypatch: pytest.MonkeyPatch) -> None:
    def tarda(comando: list[str], **kwargs: Any) -> None:
        raise subprocess.TimeoutExpired(comando, 1)

    monkeypatch.setattr("diario.llm.claude_code.subprocess.run", tarda)
    with pytest.raises(ErrorLLMTransitorio, match="tardó"):
        _pedir(ClienteClaudeCode(timeout_segundos=1))


def test_sin_ejecutable_es_fatal(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("diario.llm.claude_code.shutil.which", lambda _: None)
    with pytest.raises(ErrorLLMFatal, match="No se encontró"):
        _pedir()
