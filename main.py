import asyncio
import logging
from collections import defaultdict
from time import monotonic
from typing import Dict, Set, Tuple
from urllib.parse import quote

import aiohttp
from dotenv import load_dotenv
from reolink_aio.api import Host

from env_config import load_settings

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

    settings = load_settings()
    if not all([settings.reolink_host, settings.reolink_username, settings.reolink_password]):
        raise RuntimeError(
            "Missing credentials: ensure REOLINK_HOST/USERNAME/PASSWORD or HOST/USER/PASSWORD are set in the environment."
        )

    _LOGGER.info(
        (
            "Settings loaded: host=%s, webhook_base=%s, motion_reset_delay=%.1fs, "
            "reconnect_initial=%.1fs, reconnect_max=%.1fs, motion_cooldown=%.1fs"
        ),
        settings.reolink_host,
        settings.motion_base_url,
        settings.motion_reset_delay,
        settings.reconnect_initial_delay,
        settings.reconnect_max_delay,
        settings.motion_event_cooldown,
    )

    reconnect_delay = settings.reconnect_initial_delay

    while True:
        _LOGGER.info("Connecting to Reolink device at %s", settings.reolink_host)
        host = Host(
            settings.reolink_host,
            settings.reolink_username,
            settings.reolink_password
        )
        _LOGGER.debug("Created Host instance with stream=%s protocol=%s", host.stream if hasattr(host, "stream") else "unknown", getattr(host, "_protocol", "unknown"))
        session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5))
        _LOGGER.debug("HTTP client session created with timeout=5s")
        pending_tasks: Set[asyncio.Task] = set()
        last_motion_event_at: Dict[Tuple[int, str], float] = {}
        loop = asyncio.get_running_loop()

        async def trigger_motion(camera_name: str, channel: int) -> None:
            name_for_url = camera_name.strip() if camera_name and camera_name.strip() else f"channel-{channel}"
            encoded_name = quote(name_for_url, safe="")
            motion_url = f"{settings.motion_base_url}/motion?{encoded_name}"
            reset_url = f"{settings.motion_base_url}/motion/reset?{encoded_name}"

            try:
                async with session.get(motion_url) as response:
                    body = await response.text()
                    if response.status >= 400:
                        raise RuntimeError(f"status HTTP {response.status}")
                _LOGGER.info(
                    "Inviata notifica movimento per %s (%s) [status=%s, body_len=%s]",
                    name_for_url,
                    motion_url,
                    response.status,
                    len(body),
                )
            except Exception as err:
                _LOGGER.warning("Errore durante la notifica di movimento per %s: %s", name_for_url, err)

            await asyncio.sleep(settings.motion_reset_delay)

            try:
                async with session.get(reset_url) as response:
                    body = await response.text()
                    if response.status >= 400:
                        raise RuntimeError(f"status HTTP {response.status}")
                _LOGGER.info(
                    "Reset movimento per %s (%s) [status=%s, body_len=%s]",
                    name_for_url,
                    reset_url,
                    response.status,
                    len(body),
                )
            except Exception as err:
                _LOGGER.warning("Errore durante il reset di movimento per %s: %s", name_for_url, err)

        should_reconnect = False

        try:
            # connect and obtain/cache device settings and capabilities
            await host.get_host_data()
            _LOGGER.info(
                "Host data retrieved: cameras=%s, channels=%s",
                host.num_cameras if hasattr(host, "num_cameras") else "unknown",
                getattr(host, "channels", []),
            )
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
                _LOGGER.info(
                    "Initial AI state for camera '%s' (channel %s): %s",
                    host.camera_name(channel),
                    channel,
                    {label: ai_state_cache[channel][label] for label in TRACKED_AI_EVENTS},
                )

            def ai_event_callback() -> None:
                for channel in host.channels:
                    camera_name = host.camera_name(channel)
                    channel_cache = ai_state_cache.setdefault(channel, {})
                    for label, object_types in TRACKED_AI_EVENTS.items():
                        detected = any(bool(host.ai_detected(channel, obj_type)) for obj_type in object_types)
                        previous = channel_cache.get(label, False)
                        if detected and not previous:
                            event_key = (channel, label)
                            now = monotonic()
                            last_trigger_time = last_motion_event_at.get(event_key)
                            if last_trigger_time is not None and now - last_trigger_time < settings.motion_event_cooldown:
                                remaining = settings.motion_event_cooldown - (now - last_trigger_time)
                                _LOGGER.info(
                                    "Ignoro il rilevamento %s per la telecamera %s (canale %s): ancora %.1fs di cooldown",
                                    label,
                                    camera_name,
                                    channel,
                                    remaining,
                                )
                                channel_cache[label] = detected
                                continue
                            _LOGGER.info(
                                "Rilevamento %s dalla telecamera %s (canale %s)",
                                label,
                                camera_name,
                                channel,
                            )
                            last_motion_event_at[event_key] = now
                            task = loop.create_task(trigger_motion(camera_name, channel))
                            _LOGGER.info(
                                "Scheduling motion notification task for camera '%s' (channel %s) due to %s detection",
                                camera_name,
                                channel,
                                label,
                            )
                            pending_tasks.add(task)
                            task.add_done_callback(lambda fut: pending_tasks.discard(fut))
                        elif not detected and previous:
                            _LOGGER.info(
                                "Fine rilevamento %s per la telecamera %s (canale %s)",
                                label,
                                camera_name,
                                channel,
                            )
                        channel_cache[label] = detected

            # Register callback and subscribe to events
            host.baichuan.register_callback("ai_event_logger", ai_event_callback)
            _LOGGER.debug("Callback 'ai_event_logger' registered on Baichuan client")
            await host.baichuan.subscribe_events()
            _LOGGER.info("Subscribed to Baichuan events")
            reconnect_delay = settings.reconnect_initial_delay

            # Process TCP events until interrupted
            while True:
                if hasattr(host.baichuan, "check_subscribe_events"):
                    _LOGGER.debug("Running Baichuan subscription health check")
                    await host.baichuan.check_subscribe_events()
                await asyncio.sleep(1)
        except (asyncio.CancelledError, KeyboardInterrupt):
            _LOGGER.info("Interruzione richiesta dall'utente, chiusura in corso...")
            raise
        except Exception as err:
            should_reconnect = True
            _LOGGER.error("Connection to Reolink device lost: %s", err, exc_info=True)
        finally:
            host.baichuan.unregister_callback("ai_event_logger")
            try:
                _LOGGER.debug("Unsubscribing from Baichuan events")
                await host.baichuan.unsubscribe_events()
            except Exception as err:
                _LOGGER.warning("Errore durante l'annullamento dell'iscrizione agli eventi: %s", err)
            try:
                _LOGGER.debug("Logging out from Reolink host")
                await host.logout()
            except Exception as err:
                _LOGGER.warning("Errore durante il logout dal dispositivo: %s", err)
            if pending_tasks:
                _LOGGER.info("Waiting for %s pending HTTP tasks to complete", len(pending_tasks))
                await asyncio.gather(*pending_tasks, return_exceptions=True)
            _LOGGER.debug("Closing HTTP session")
            await session.close()

        if should_reconnect:
            delay = reconnect_delay
            _LOGGER.info("Tentativo di riconnessione tra %.1f secondi", delay)
            await asyncio.sleep(delay)
            reconnect_delay = min(reconnect_delay * 2, settings.reconnect_max_delay)
            continue

        break

if __name__ == "__main__":
    asyncio.run(tcp_push_demo())
