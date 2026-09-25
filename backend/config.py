"""Configuración del backend leída de variables de entorno (backend/.env)."""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent
REPO_DIR = BACKEND_DIR.parent

load_dotenv(BACKEND_DIR / ".env")

# Presupuesto de tiempo (segundos de plazo on-chain que deben quedar).
MIN_SECONDS_TO_EVALUATE = 120   # /evaluate rechaza con DEADLINE_TOO_CLOSE por debajo
GEMINI_TIMEOUT_SECS = 20     # tope por intento a Gemini
RELEASE_BUDGET_SECS = 30        # preparar, firmar, enviar y confirmar el release
# Antes de cada intento a Gemini debe alcanzar para el intento y para el release.
GEMINI_ATTEMPT_BUDGET_SECS = GEMINI_TIMEOUT_SECS + RELEASE_BUDGET_SECS

MAX_SUBMISSIONS = 3
MAX_DEADLINE_MINUTES = 60 * 24 * 7  # 7 días; el TTL que el contrato extiende es de 30 días
MAX_CODE_BYTES = 10 * 1024


class ConfigError(RuntimeError):
    pass


def _flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes")


@dataclass(frozen=True)
class Settings:
    use_vertex: bool
    gemini_api_key: str | None
    gcp_project: str | None
    gcp_location: str | None
    gemini_model: str
    arbiter_secret: str
    contract_id: str
    usdc_sac_id: str
    rpc_url: str
    network_passphrase: str
    frontend_origin: str
    state_file: Path

    def __repr__(self) -> str:  # nunca imprimir secretos
        return (f"Settings(use_vertex={self.use_vertex}, model={self.gemini_model}, "
                f"contract_id={self.contract_id}, state_file={self.state_file})")


def load_settings() -> Settings:
    use_vertex = _flag("GOOGLE_GENAI_USE_VERTEXAI")
    api_key = os.environ.get("GEMINI_API_KEY") or None
    project = os.environ.get("GOOGLE_CLOUD_PROJECT") or None
    location = os.environ.get("GOOGLE_CLOUD_LOCATION") or None
    if use_vertex and not (project and location):
        raise ConfigError("Con GOOGLE_GENAI_USE_VERTEXAI=true faltan GOOGLE_CLOUD_PROJECT o GOOGLE_CLOUD_LOCATION")
    if not use_vertex and not api_key:
        raise ConfigError("Faltan credenciales de Gemini: GOOGLE_GENAI_USE_VERTEXAI=true o GEMINI_API_KEY")

    required = ["GEMINI_MODEL", "ARBITER_SECRET_KEY", "CONTRACT_ID", "USDC_SAC_ID",
                "STELLAR_RPC_URL", "NETWORK_PASSPHRASE"]
    missing = [k for k in required if not os.environ.get(k)]
    if missing:
        raise ConfigError(f"Faltan variables de entorno: {', '.join(missing)}")

    state_file = Path(os.environ.get("STATE_FILE") or "backend/state.json")
    if not state_file.is_absolute():
        state_file = REPO_DIR / state_file

    return Settings(
        use_vertex=use_vertex,
        gemini_api_key=api_key,
        gcp_project=project,
        gcp_location=location,
        gemini_model=os.environ["GEMINI_MODEL"],
        arbiter_secret=os.environ["ARBITER_SECRET_KEY"],
        contract_id=os.environ["CONTRACT_ID"],
        usdc_sac_id=os.environ["USDC_SAC_ID"],
        rpc_url=os.environ["STELLAR_RPC_URL"],
        network_passphrase=os.environ["NETWORK_PASSPHRASE"],
        frontend_origin=os.environ.get("FRONTEND_ORIGIN", "http://localhost:3000"),
        state_file=state_file,
    )
