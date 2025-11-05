import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    reolink_host: str
    reolink_username: str
    reolink_password: str
    motion_base_url: str
    motion_reset_delay: float
    reconnect_initial_delay: float
    reconnect_max_delay: float
    motion_event_cooldown: float


def load_settings() -> Settings:
    motion_base_url = (os.getenv("MOTION_BASE_URL") or "http://10.0.1.4:8080").rstrip("/")

    def _float_env(name: str, default: float) -> float:
        try:
            return float(os.getenv(name, default))
        except (TypeError, ValueError):
            return default

    motion_reset_delay = _float_env("MOTION_RESET_DELAY_SECONDS", 5.0)
    reconnect_initial_delay = _float_env("RECONNECT_INITIAL_DELAY", 5.0)
    reconnect_max_delay = _float_env("RECONNECT_MAX_DELAY", 60.0)
    motion_event_cooldown = _float_env("MOTION_EVENT_COOLDOWN_SECONDS", 60.0)

    return Settings(
        reolink_host=os.getenv("REOLINK_HOST") or os.getenv("HOST", ""),
        reolink_username=os.getenv("REOLINK_USERNAME") or os.getenv("USER", ""),
        reolink_password=os.getenv("REOLINK_PASSWORD") or os.getenv("PASSWORD", ""),
        motion_base_url=motion_base_url,
        motion_reset_delay=motion_reset_delay,
        reconnect_initial_delay=reconnect_initial_delay,
        reconnect_max_delay=reconnect_max_delay,
        motion_event_cooldown=motion_event_cooldown,
    )
