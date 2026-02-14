# Docker Setup for Deye Dashboard

This document explains how to build and run the Deye Dashboard using Docker.

## Prerequisites

- Docker installed on your system
- Docker Compose (optional, but recommended)
- Environment variables configured (see below)

## Quick Start

### Using Docker Compose (Recommended)

1. **Create a `.env` file** with your configuration:

```bash
cp .env.example .env
# Edit .env with your inverter IP, logger serial, and other settings
```

2. **Build and start the dashboard:**

```bash
docker-compose up -d
```

3. **Access the dashboard:**

Open http://localhost:8080 in your browser

4. **View logs:**

```bash
docker-compose logs -f
```

5. **Stop the dashboard:**

```bash
docker-compose down
```

### Using Docker CLI

1. **Build the image:**

```bash
docker build -t deye-dashboard:latest .
```

2. **Create a `.env` file:**

```bash
cp .env.example .env
# Edit .env with your configuration
```

3. **Run the container:**

```bash
docker run -d \
  --name deye-dashboard \
  -p 8080:8080 \
  --env-file .env \
  -v $(pwd)/data:/app/data \
  --restart unless-stopped \
  deye-dashboard:latest
```

4. **View logs:**

```bash
docker logs -f deye-dashboard
```

5. **Stop the container:**

```bash
docker stop deye-dashboard
docker rm deye-dashboard
```

## Configuration

All configuration is done through environment variables in your `.env` file:

### Required Settings

| Variable | Description | Example |
|----------|-------------|---------|
| `INVERTER_IP` | IP address of your Deye inverter | `192.168.1.100` |
| `LOGGER_SERIAL` | Serial number of the Solarman Wi-Fi logger | `1234567890` |

### Optional Settings

| Variable | Description | Default |
|----------|-------------|---------|
| `WEATHER_LATITUDE` | Latitude for weather forecast | `50.4501` |
| `WEATHER_LONGITUDE` | Longitude for weather forecast | `30.5234` |
| `INVERTER_PHASES` | Number of phases (1 or 3) | auto-detected |
| `INVERTER_HAS_BATTERY` | Whether battery is connected (true/false) | auto-detected |
| `INVERTER_PV_STRINGS` | Number of PV strings (1 or 2) | auto-detected |
| `INVERTER_HAS_GENERATOR` | Whether generator is connected | false |
| `OUTAGE_PROVIDER` | Outage provider: `lvivoblenergo`, `yasno`, or `none` | `none` |
| `OUTAGE_GROUP` | Your outage queue/group number | — |
| `TELEGRAM_ENABLED` | Enable Telegram bot | false |
| `TELEGRAM_BOT_TOKEN` | Bot token from @BotFather | — |
| `TELEGRAM_ALLOWED_USERS` | Comma-separated Telegram user IDs | — |
| `TELEGRAM_PUBLIC` | Allow any user to query bot | false |

### Data Persistence

The container mounts a `data` volume at `/app/data` for persistent storage of:

- Outage history (`outage_history.json`)
- Phase statistics (`phase_stats.json`)
- Phase history (`phase_history.json`)

The `data` directory is created automatically on first run.

## Volumes and Ports

### Ports

- **8080** — Flask web application

### Volumes

- **`./data:/app/data`** — Persistent data storage

## Environment Variables

### Using with docker-compose

Create a `.env` file in the project root:

```env
INVERTER_IP=192.168.1.100
LOGGER_SERIAL=1234567890
WEATHER_LATITUDE=50.4501
WEATHER_LONGITUDE=30.5234
OUTAGE_PROVIDER=lvivoblenergo
OUTAGE_GROUP=1.1
TELEGRAM_ENABLED=false
```

The values are automatically loaded by `docker-compose`.

### Using with docker run

Pass environment variables with `--env-file`:

```bash
docker run -d \
  --name deye-dashboard \
  -p 8080:8080 \
  --env-file .env \
  -v $(pwd)/data:/app/data \
  deye-dashboard:latest
```

Or set individual variables:

```bash
docker run -d \
  --name deye-dashboard \
  -p 8080:8080 \
  -e INVERTER_IP=192.168.1.100 \
  -e LOGGER_SERIAL=1234567890 \
  -v $(pwd)/data:/app/data \
  deye-dashboard:latest
```

## Networking

### Docker Compose

The service runs on a named bridge network `deye-network` for isolation.

### Access from Host

- Use `http://localhost:8080` on the host machine
- The container can reach other local services on the host network (e.g., inverter at `192.168.1.100`)

### Access from Other Containers

If you want to add other services (e.g., Grafana, monitoring), use the service name:

```yaml
# In docker-compose.yml for another service
depends_on:
  - deye-dashboard
environment:
  DASHBOARD_URL: http://deye-dashboard:8080
```

## Health Checks

The container includes a built-in health check that:

- Pings the `/api/data` endpoint every 30 seconds
- Waits 40 seconds before starting health checks
- Considers the container unhealthy after 3 failed checks

Check the health status:

```bash
docker ps  # Shows health status
# or
docker inspect deye-dashboard --format='{{.State.Health.Status}}'
```

## Building and Publishing

### Build with custom tags

```bash
docker build -t myregistry/deye-dashboard:1.0.0 .
docker build -t myregistry/deye-dashboard:latest .
```

### Push to registry

```bash
docker login
docker push myregistry/deye-dashboard:1.0.0
docker push myregistry/deye-dashboard:latest
```

### Build for multiple architectures (requires buildx)

```bash
docker buildx build --platform linux/amd64,linux/arm64 -t myregistry/deye-dashboard:latest .
```

## Troubleshooting

### Container won't start

Check the logs:

```bash
docker-compose logs deye-dashboard
# or
docker logs deye-dashboard
```

### Cannot connect to inverter

Ensure the inverter IP is correct and reachable from the container:

```bash
docker exec deye-dashboard ping 192.168.1.100
```

If the inverter is on a different network, you may need to use `--network host` or adjust network settings.

### Missing data files

Ensure the `data` directory has write permissions:

```bash
mkdir -p data
chmod 777 data
```

### High memory usage

Monitor resource usage:

```bash
docker stats deye-dashboard
```

Limit resources in `docker-compose.yml`:

```yaml
services:
  deye-dashboard:
    # ... other config ...
    deploy:
      resources:
        limits:
          cpus: '0.5'
          memory: 256M
        reservations:
          cpus: '0.25'
          memory: 128M
```

## Updating

### With docker-compose

```bash
docker-compose pull
docker-compose up -d
```

### With docker

```bash
docker pull deye-dashboard:latest
docker stop deye-dashboard
docker rm deye-dashboard
docker run -d \
  --name deye-dashboard \
  -p 8080:8080 \
  --env-file .env \
  -v $(pwd)/data:/app/data \
  deye-dashboard:latest
```

## Production Deployment

For production, consider:

1. **Use a reverse proxy** (nginx, Traefik) for SSL/TLS and routing
2. **Set resource limits** to prevent container from consuming all resources
3. **Use named volumes** instead of bind mounts for better portability
4. **Run with read-only root filesystem** when possible
5. **Use a secrets manager** for sensitive data (Telegram tokens, etc.)
6. **Monitor logs** with a centralized logging solution

Example production setup with nginx:

```yaml
version: '3.8'

services:
  deye-dashboard:
    build: .
    container_name: deye-dashboard
    env_file: .env
    volumes:
      - dashboard-data:/app/data
    networks:
      - deye-network
    restart: unless-stopped
    deploy:
      resources:
        limits:
          cpus: '0.5'
          memory: 256M

  nginx:
    image: nginx:alpine
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf:ro
      - ./ssl:/etc/nginx/ssl:ro
    depends_on:
      - deye-dashboard
    networks:
      - deye-network
    restart: unless-stopped

volumes:
  dashboard-data:

networks:
  deye-network:
```

## See Also

- [Docker Documentation](https://docs.docker.com/)
- [Docker Compose Documentation](https://docs.docker.com/compose/)
- [Main README](README.md)

