from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    port_min: int
    port_max: int
    host: str


def get_settings() -> Settings:
    data_dir = Path(os.getenv("STREAMLIT_HOST_DATA", "./data")).resolve()
    port_min = int(os.getenv("STREAMLIT_HOST_PORT_MIN", "8501"))
    port_max = int(os.getenv("STREAMLIT_HOST_PORT_MAX", "8999"))
    host = os.getenv("STREAMLIT_HOST_BIND", "0.0.0.0")
    return Settings(data_dir=data_dir, port_min=port_min, port_max=port_max, host=host)


