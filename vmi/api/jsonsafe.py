"""One place that makes any analysis payload JSON-safe (numpy scalars/arrays, NaN/inf, dataclasses, pandas,
dates, sets). Used as the app's default response class so no endpoint can fail serialisation again."""
from __future__ import annotations

import dataclasses
import datetime as dt
import json
import math
from enum import Enum
from typing import Any

from fastapi.responses import JSONResponse


def clean(o: Any) -> Any:
    if o is None or isinstance(o, (str, bool, int)):
        return o
    if isinstance(o, float):
        return o if math.isfinite(o) else None
    if isinstance(o, dict):
        return {str(k): clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple, set, frozenset)):
        return [clean(v) for v in o]
    if isinstance(o, Enum):
        return clean(o.value)
    if isinstance(o, (dt.datetime, dt.date)):
        return o.isoformat()
    if dataclasses.is_dataclass(o) and not isinstance(o, type):
        return clean(dataclasses.asdict(o))
    mod = type(o).__module__
    if mod.startswith("numpy"):
        if hasattr(o, "tolist"):
            return clean(o.tolist())
        return clean(o.item())
    if mod.startswith("pandas"):
        if hasattr(o, "isoformat"):
            return o.isoformat()
        if hasattr(o, "to_dict"):
            return clean(o.to_dict())
    if hasattr(o, "to_dict"):
        return clean(o.to_dict())
    if hasattr(o, "model_dump"):
        return clean(o.model_dump())
    return str(o)


class SafeJSONResponse(JSONResponse):
    def render(self, content: Any) -> bytes:
        return json.dumps(clean(content), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
