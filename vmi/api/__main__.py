"""python -m vmi.api  → start the local VMI server."""
import uvicorn

from vmi.config import get_settings

if __name__ == "__main__":
    s = get_settings()
    uvicorn.run("vmi.api.app:app", host=s.host, port=s.port, log_level="info")
