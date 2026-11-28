"""User preferences for local AI, separate from investing rules and model downloads."""
from __future__ import annotations

import logging
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from vmi.config import get_settings

OverviewDepth = Literal["quick", "standard", "deep"]
log = logging.getLogger(__name__)


class AISettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    overview_depth: OverviewDepth = "quick"
    cache_overviews: bool = True
    max_run_minutes: int = Field(40, ge=5, le=40)
    max_gpu_temp_c: int = Field(85, ge=65, le=85)
    override_ram_guard: bool = False
    min_free_ram_mb: int = Field(1536, ge=1536, le=8192)


def _path() -> Path:
    return get_settings().data_dir / "ai_settings.json"


def load() -> AISettings:
    try:
        return AISettings.model_validate_json(_path().read_text(encoding="utf-8"))
    except FileNotFoundError:
        return AISettings()
    except (OSError, ValueError) as exc:
        log.warning("Could not read AI settings; using defaults: %s", exc)
        return AISettings()


def save(settings: AISettings) -> AISettings:
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = None
    try:
        with NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as f:
            temp = Path(f.name)
            f.write(settings.model_dump_json(indent=2))
        temp.replace(path)
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)
    return settings
