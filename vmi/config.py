"""Runtime settings (environment / .env driven). VMI methodology thresholds live in vmi.rules."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="VMI_", env_file=".env", extra="ignore")

    data_dir: Path = ROOT / "data"
    db_url: str = ""  # default: sqlite in data_dir

    # SEC requires a descriptive User-Agent with contact info (fair-access policy).
    sec_user_agent: str = "VMI-Toolkit research vmi-toolkit@example.com"
    sec_max_rps: float = 8.0  # SEC limit is 10 req/s; stay under it

    # Interactive Brokers (TWS / IB Gateway). Paper 7497 / live 7496; Gateway paper 4002 / live 4001.
    ib_enabled: bool = True
    ib_host: str = "127.0.0.1"
    ib_port: int = 0  # 0 = find it: tries the usual ports of TWS and IB Gateway (see vmi.data.ib.AUTO_PORTS)
    ib_client_id: int = 17
    ib_market_data_type: int = 1  # 1 live, 2 frozen, 3 delayed, 4 delayed-frozen
    ib_connect_timeout: float = 4.0
    # IBKR Client Portal Gateway (a separate IBKR app, not TWS) for the Fundamentals Explorer backend
    # (vmi.data.ibportal). Default: where the gateway listens. If it is not running or not logged in, the app
    # quietly skips it and rechecks every minute. Empty string = never try. Log the gateway in with a DIFFERENT
    # username than TWS (e.g. the paper login): see Log.md.
    ib_cp_url: str = "https://localhost:5000"
    ib_cp_verify: bool = False  # the local gateway uses a self-signed certificate
    ib_cp_max_rps: float = 5.0  # stay well under IBKR's Web API rate limit (~10 requests/s)

    # Cache TTLs (seconds)
    ttl_quote: int = 15
    ttl_history: int = 6 * 3600
    ttl_fundamentals: int = 7 * 24 * 3600
    ttl_estimates: int = 3 * 24 * 3600
    ttl_ib_portal: int = 14 * 24 * 3600  # IB gateway data (statements + analyst growth); refreshed by `sync`
    ttl_universe: int = 24 * 3600
    ttl_option_chain: int = 60

    scanner_workers: int = 4
    host: str = "0.0.0.0"
    port: int = 8000

    @property
    def cache_dir(self) -> Path:
        p = self.data_dir / "cache"
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def database_url(self) -> str:
        if self.db_url:
            return self.db_url
        self.data_dir.mkdir(parents=True, exist_ok=True)
        return f"sqlite:///{self.data_dir / 'vmi.db'}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
