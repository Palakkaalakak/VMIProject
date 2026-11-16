"""Runtime mode: "fundamental review" = the owner is only reviewing watchlists/fundamentals, so the app must not look for
IB Gateway or open the IBKR sign-in window. Default off (the app keeps listening for Gateway). Persisted in the cache DB."""
from vmi.data.cache import get_cache

KEY = "mode:fundamental_review"
FOREVER = 10 * 365 * 86400


def fundamental_review() -> bool:
    return bool(get_cache().get(KEY, FOREVER))


def set_fundamental_review(on: bool) -> bool:
    get_cache().set(KEY, bool(on))
    return bool(on)
