import asyncio
import logging
import os
from collections import defaultdict
from typing import Dict, Set
from urllib.parse import quote

import aiohttp
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
    motion_base_url = os.getenv("MOTION_BASE_URL").rstrip("/")
    motion_reset_delay = float(os.getenv("MOTION_RESET_DELAY_SECONDS", 5))

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
    session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5))
    pending_tasks: Set[asyncio.Task] = set()
    loop = asyncio.get_running_loop()

    async def trigger_motion(camera_name: str, channel: int) -> None:
        name_for_url = camera_name.strip() if camera_name and camera_name.strip() else f"channel-{channel}"
        encoded_name = quote(name_for_url, safe="")
        motion_url = f"{motion_base_url}/motion?{encoded_name}"
        reset_url = f"{motion_base_url}/motion/reset?{encoded_name}"

        try:
            async with session.get(motion_url) as response:
                await response.text()
                if response.status >= 400:
                    raise RuntimeError(f"status HTTP {response.status}")
            _LOGGER.info("Inviata notifica movimento per %s (%s)", name_for_url, motion_url)
        except Exception as err:
            _LOGGER.warning("Errore durante la notifica di movimento per %s: %s", name_for_url, err)

        await asyncio.sleep(motion_reset_delay)

        try:
            async with session.get(reset_url) as response:
                await response.text()
                if response.status >= 400:
                    raise RuntimeError(f"status HTTP {response.status}")
            _LOGGER.info("Reset movimento per %s (%s)", name_for_url, reset_url)
        except Exception as err:
            _LOGGER.warning("Errore durante il reset di movimento per %s: %s", name_for_url, err)

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
                        task = loop.create_task(trigger_motion(camera_name, channel))
                        pending_tasks.add(task)
                        task.add_done_callback(lambda fut: pending_tasks.discard(fut))
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
        try:
            await host.baichuan.unsubscribe_events()
        except Exception as err:
            _LOGGER.warning("Errore durante l'annullamento dell'iscrizione agli eventi: %s", err)
        try:
            await host.logout()
        except Exception as err:
            _LOGGER.warning("Errore durante il logout dal dispositivo: %s", err)
        if pending_tasks:
            await asyncio.gather(*pending_tasks, return_exceptions=True)
        await session.close()

if __name__ == "__main__":
    asyncio.run(tcp_push_demo())
