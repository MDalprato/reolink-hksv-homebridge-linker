import asyncio
import logging
import os
from collections import defaultdict
from typing import Dict

from reolink_aio.api import Host
from dotenv import load_dotenv

logging.basicConfig(level="INFO")
_LOGGER = logging.getLogger(__name__)

TRACKED_AI_EVENTS = {
    "persona": ("person", "people"),
    "auto": ("vehicle",),
    "animale": ("pet", "dog_cat"),
}

async def tcp_push_demo():
    # initialize the host
    load_dotenv()
    
    reolink_host = os.getenv("REOLINK_HOST") or os.getenv("HOST")
    reolink_username = os.getenv("REOLINK_USERNAME") or os.getenv("USER")
    reolink_password = os.getenv("REOLINK_PASSWORD") or os.getenv("PASSWORD")

    print('Connecting to Reolink device at', reolink_host);
    
    if not all([reolink_host, reolink_username, reolink_password]):
        raise RuntimeError(
            "Missing credentials: ensure REOLINK_HOST/USERNAME/PASSWORD or HOST/USER/PASSWORD are set in the environment."
        )
    host = Host(
        reolink_host,
        reolink_username,
        reolink_password
    )
    # connect and obtain/cache device settings and capabilities
    await host.get_host_data()
    try:
        try:
            await host.get_ai_state_all_ch()
        except Exception as err:
            _LOGGER.warning("Impossibile recuperare lo stato AI iniziale: %s", err)

        ai_state_cache: Dict[int, Dict[str, bool]] = defaultdict(dict)

        for channel in host.channels:
            for label, object_types in TRACKED_AI_EVENTS.items():
                ai_state_cache[channel][label] = any(
                    bool(host.ai_detected(channel, obj_type)) for obj_type in object_types
                )

        def ai_event_callback() -> None:
            for channel in host.channels:
                camera_name = host.camera_name(channel)
                channel_cache = ai_state_cache.setdefault(channel, {})
                for label, object_types in TRACKED_AI_EVENTS.items():
                    detected = any(bool(host.ai_detected(channel, obj_type)) for obj_type in object_types)
                    previous = channel_cache.get(label, False)
                    if detected and not previous:
                        _LOGGER.info(
                            "Rilevamento %s dalla telecamera %s (canale %s)",
                            label,
                            camera_name,
                            channel,
                        )
                    channel_cache[label] = detected

        # Register callback and subscribe to events
        host.baichuan.register_callback("ai_event_logger", ai_event_callback)
        await host.baichuan.subscribe_events()
        # Process TCP events until interrupted
        while True:
            await asyncio.sleep(1)
    except (asyncio.CancelledError, KeyboardInterrupt):
        _LOGGER.info("Interruzione richiesta dall'utente, chiusura in corso...")
    finally:
        host.baichuan.unregister_callback("ai_event_logger")
        await host.baichuan.unsubscribe_events()
        await host.logout()

if __name__ == "__main__":
    asyncio.run(tcp_push_demo())
