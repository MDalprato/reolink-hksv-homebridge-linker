# Reolink Event Relay

This repository contains a small asynchronous Python script that connects to a Reolink camera or NVR, listens for AI detection events (people, vehicles, pets), and forwards those events to an external HTTP endpoint. After a short delay it sends a reset call, allowing downstream automation systems to react to motion while keeping their state in sync.

## Features
- Subscribes to the Reolink Baichuan TCP push channel for near real-time AI detections.
- Logs detections with both channel index and the camera name supplied by the device.
- Issues HTTP callbacks for every new detection and schedules an automatic reset after a configurable delay.
- Automatically retries the connection with exponential backoff whenever the device disconnects.
- Gracefully handles shutdown (Ctrl+C) and cleans up pending network requests.

## Requirements
- Python 3.10+ (a virtual environment is recommended).
- `reolink-aio`, `aiohttp`, and `python-dotenv` Python packages.
- Network access to both the Reolink device and the external HTTP endpoint.

### Installing dependencies
```bash
python3 -m venv venv
source venv/bin/activate
pip install reolink-aio aiohttp python-dotenv
```

## Configuration
Create a `.env` file (or export environment variables) with the following entries:

| Variable | Description |
| --- | --- |
| `REOLINK_HOST` / `HOST` | IP or hostname of the Reolink device. |
| `REOLINK_USERNAME` / `USER` | Username for the device. |
| `REOLINK_PASSWORD` / `PASSWORD` | Password for the device. |
| `MOTION_BASE_URL` | Base URL for the motion webhook (default `http://10.0.1.4:8080`). Trailing slashes are trimmed automatically. |
| `MOTION_RESET_DELAY_SECONDS` | Seconds to wait before issuing the reset callback (default `5`). |
| `RECONNECT_INITIAL_DELAY` | Seconds to wait before the first reconnect attempt after a disconnection (default `5`). |
| `RECONNECT_MAX_DELAY` | Maximum backoff delay between reconnect attempts (default `60`). |

The script accepts either the prefixed `REOLINK_*` variables or the shorter alternatives to make it compatible with existing setups.

## Running the script
```bash
venv/bin/python main.py
```

The script will:
1. Connect to the configured Reolink host and fetch device capabilities.
2. Subscribe to Baichuan push events.
3. For each new AI detection (person, vehicle, pet), log the event, call  
   `GET {MOTION_BASE_URL}/motion?{camera name}`, and five seconds later call  
   `GET {MOTION_BASE_URL}/motion/reset?{camera name}`. Camera names are URL-encoded automatically.
4. If the connection drops, automatically back off and retry the login.
5. Continue running until interrupted. Press `Ctrl+C` to stop; pending HTTP requests complete, the Baichuan subscription is released, and the session logs out cleanly.

## Running in Docker

Build the container (one time):
```bash
docker build -t reolink-event-relay .
```

Run with environment variables mapped from your shell or an `.env` file:
```bash
docker run --rm --env-file .env reolink-event-relay
```

Follow logs from another shell:
```bash
docker logs -f <container_id>
```

Override individual variables directly:
```bash
docker run --rm \
  -e REOLINK_HOST=10.0.1.2 \
  -e REOLINK_USERNAME=admin \
  -e REOLINK_PASSWORD=secret \
  -e MOTION_BASE_URL=http://10.0.1.4:8080 \
  reolink-event-relay
```

Mount a host directory for log files (optional):
```bash
docker run --rm --env-file .env -v $(pwd)/logs:/logs reolink-event-relay
```

### Docker Compose

Example `docker-compose.yml` entry:
```yaml
services:
  reolink-event-relay:
    image: reolink-event-relay
    build: .
    env_file: .env
    restart: unless-stopped
```

Launch with:
```bash
docker compose up -d
```

The container entrypoint runs `python main.py`. Mount additional volumes if you need to persist logs or use alternative configuration files.

## Notes
- If the camera name is missing, the script falls back to `channel-{index}` when building the webhook URL.
- The HTTP callbacks treat any response code ≥ 400 as an error and log a warning.
- You can extend `TRACKED_AI_EVENTS` in `main.py` if you want to react to additional AI categories supported by your device.
