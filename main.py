from reolink_aio.api import Host
import asyncio
import logging

logging.basicConfig(level="INFO")
_LOGGER = logging.getLogger(__name__)

def callback() -> None:
    _LOGGER.info("Callback called")

async def tcp_push_demo():
    # initialize the host
    host = Host(host="192.168.1.109", username="admin", password="admin1234")
    # connect and obtain/cache device settings and capabilities
    await host.get_host_data()
    # Register callback and subscribe to events
    host.baichuan.register_callback("unique_id_string", callback)
    await host.baichuan.subscribe_events()
    # Process TCP events for 2 minutes
    await asyncio.sleep(120)
    # unsubscribe and close the device connection
    await host.baichuan.unsubscribe_events()
    await host.logout()

if __name__ == "__main__":
    asyncio.run(tcp_push_demo())