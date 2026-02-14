# Deye Solar Dashboard

A web dashboard for monitoring Deye solar inverters in real-time. Supports both single-phase (e.g. SUN-6K-SG03LP1) and 3-phase hybrid models. Displays solar production, battery status, grid power, home consumption, weather conditions, and power outage schedules.

![Dashboard Preview](docs/preview.png)

## How It Works (for non-technical users)

This project is a **home energy dashboard** — a web page that shows you what your solar panels are producing, how much battery you have left, whether you're using grid power, and when the next power outage is scheduled.

### What you need

1. **A Deye solar inverter** with a Solarman Wi-Fi logger stick (the small antenna plugged into your inverter). Most Deye hybrid inverters come with one.

2. **A small home computer** that runs 24/7 on your local network. The best option is a **Raspberry Pi Zero 2W** (~$15) or any Raspberry Pi model. It uses very little power and sits quietly on your network. Any Linux computer (old laptop, mini PC, etc.) works too.

3. **Your home Wi-Fi network** — both the inverter's logger stick and the Raspberry Pi must be connected to the same network.

### How it works

```
Solar Panels → Deye Inverter → Wi-Fi Logger Stick
                                       ↓
                              Your Home Network
                                       ↓
                              Raspberry Pi (runs this dashboard)
                                       ↓
                              Your Phone / Tablet / PC (opens the dashboard in a browser)
```

The Raspberry Pi reads data from your inverter every 60 seconds over your local network. It then shows this data on a web page you can open from any device in your home — phone, tablet, or computer — by going to the Raspberry Pi's address in a browser (e.g. `http://192.168.1.50:8080`).

### Setup overview

1. **Get a Raspberry Pi** and install Raspberry Pi OS on it (many YouTube tutorials available)
2. **Connect it to your Wi-Fi** and make sure it has a fixed IP address
3. **Run the deploy script** from your computer — it copies everything to the Pi and starts the dashboard automatically
4. **Open the dashboard** in your browser — on first launch, a setup wizard will guide you through connecting to your inverter

You don't need to be a programmer, but you should be comfortable with basic computer tasks like connecting to Wi-Fi and following step-by-step instructions. If you have a tech-savvy friend or family member, ask them to help with the initial setup — after that, the dashboard runs on its own.

---

## Як це працює (для нетехнічних користувачів)

Цей проект — це **домашня енергетична панель** — веб-сторінка, яка показує, скільки електроенергії виробляють ваші сонячні панелі, який заряд акумулятора, чи використовуєте ви електрику з мережі, та коли заплановане наступне відключення.

### Що вам потрібно

1. **Сонячний інвертор Deye** з Wi-Fi логером Solarman (маленька антена, підключена до інвертора). Більшість гібридних інверторів Deye комплектуються таким.

2. **Невеликий домашній комп'ютер**, який працює постійно у вашій локальній мережі. Найкращий варіант — **Raspberry Pi Zero 2W** (~$15) або будь-яка модель Raspberry Pi. Він споживає дуже мало енергії та тихо працює у вашій мережі. Будь-який Linux-комп'ютер (старий ноутбук, міні-ПК тощо) також підійде.

3. **Ваша домашня Wi-Fi мережа** — і логер інвертора, і Raspberry Pi мають бути підключені до однієї мережі.

### Як це працює

```
Сонячні панелі → Інвертор Deye → Wi-Fi логер
                                       ↓
                              Ваша домашня мережа
                                       ↓
                              Raspberry Pi (запускає цю панель)
                                       ↓
                              Ваш телефон / планшет / ПК (відкриває панель у браузері)
```

Raspberry Pi зчитує дані з вашого інвертора кожні 60 секунд через локальну мережу. Потім він відображає ці дані на веб-сторінці, яку можна відкрити з будь-якого пристрою у вашому домі — телефону, планшета чи комп'ютера — перейшовши за адресою Raspberry Pi у браузері (наприклад, `http://192.168.1.50:8080`).

### Огляд налаштування

1. **Придбайте Raspberry Pi** та встановіть на нього Raspberry Pi OS (багато відеоінструкцій на YouTube)
2. **Підключіть його до Wi-Fi** та переконайтесь, що він має фіксовану IP-адресу
3. **Запустіть скрипт розгортання** з вашого комп'ютера — він скопіює все на Pi та автоматично запустить панель
4. **Відкрийте панель** у браузері — при першому запуску майстер налаштування допоможе вам підключитися до інвертора

Вам не потрібно бути програмістом, але ви повинні вміти виконувати базові завдання на комп'ютері, такі як підключення до Wi-Fi та слідування покроковим інструкціям. Якщо у вас є технічно обізнаний друг чи родич, попросіть їх допомогти з початковим налаштуванням — після цього панель працює самостійно.

---

## Features

- **Real-time monitoring** — solar production, battery SOC, grid power, and load consumption
- **Load analytics** — per-phase power distribution with daily statistics (3-phase systems)
- **Weather** — current conditions and forecast via Open-Meteo API
- **Outage schedule** — upcoming power outage windows (Lvivoblenergo or Yasno providers)
- **Grid outage detection** — voice alerts and browser notifications when power goes out
- **Outage history** — track and review past power outages
- **Telegram bot** — battery reports, inverter status, and Ukrainian weather poems
- **Fullscreen mode** — kiosk-friendly display with weather, grid, and battery banners
- **Responsive design** — works on desktop and mobile

## Requirements

- Python 3.7+
- Deye inverter with Solarman Wi-Fi logger
- Network access to the inverter

## Quick Start

```bash
git clone https://github.com/ivanursul/deye-dashboard.git
cd deye-dashboard
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Create a `.env` file from the example and fill in your values:

```bash
cp .env.example .env
# Edit .env with your inverter IP, logger serial, etc.
```

Run the dashboard:

```bash
python app.py
```

Open http://localhost:8080 in your browser.

## Docker

You can also run the dashboard using Docker, which is the recommended approach for production deployments.

### Using Docker Compose (Recommended)

```bash
# Create and configure .env file
cp .env.example .env
# Edit .env with your inverter IP, logger serial, etc.

# Build and start the dashboard
docker-compose up -d

# View logs
docker-compose logs -f

# Stop the dashboard
docker-compose down
```

### Using Docker CLI

```bash
# Build the image
docker build -t deye-dashboard:latest .

# Run the container
docker run -d \
  --name deye-dashboard \
  -p 8080:8080 \
  --env-file .env \
  -v $(pwd)/data:/app/data \
  --restart unless-stopped \
  deye-dashboard:latest
```

### Data Persistence

The container mounts a `data` volume at `/app/data` for persistent storage of:
- Outage history (`outage_history.json`)
- Phase statistics (`phase_stats.json`)
- Phase history (`phase_history.json`)

### Health Checks

The container includes a built-in health check that pings the `/api/data` endpoint every 30 seconds. Check the health status with:

```bash
docker ps  # Shows health status
docker inspect deye-dashboard --format='{{.State.Health.Status}}'
```

For detailed Docker configuration options, troubleshooting, and production deployment tips, see [DOCKER.md](DOCKER.md).

## Configuration

All configuration is done via environment variables, typically set in a `.env` file. See `.env.example` for a complete template.

### Inverter (required)

| Variable | Description | Example |
|----------|-------------|---------|
| `INVERTER_IP` | IP address of your Deye inverter on the local network | `192.168.1.100` |
| `LOGGER_SERIAL` | Serial number of the Solarman Wi-Fi logger (printed on the stick or found in the Solarman app) | `1234567890` |

### Inverter Capabilities (optional)

These are auto-detected at startup. Set them only if auto-detection doesn't work for your model.

| Variable | Description | Default |
|----------|-------------|---------|
| `INVERTER_PHASES` | Number of phases (`1` or `3`) | auto-detected |
| `INVERTER_HAS_BATTERY` | Whether a battery is connected (`true` / `false`) | auto-detected |
| `INVERTER_PV_STRINGS` | Number of PV strings (`1` or `2`) | auto-detected |

### Weather

| Variable | Description | Default |
|----------|-------------|---------|
| `WEATHER_LATITUDE` | Latitude for weather forecast | `50.4501` |
| `WEATHER_LONGITUDE` | Longitude for weather forecast | `30.5234` |

Coordinates are used to fetch weather data from the [Open-Meteo API](https://open-meteo.com/). Find your coordinates on [latlong.net](https://www.latlong.net/).

### Outage Schedule

| Variable | Description | Default |
|----------|-------------|---------|
| `OUTAGE_PROVIDER` | Provider name: `lvivoblenergo`, `yasno`, or `none` | `none` |
| `OUTAGE_GROUP` | Your outage queue/group number (e.g. `1.1`, `2.2`) | — |

**Yasno-specific settings** (only when `OUTAGE_PROVIDER=yasno`):

| Variable | Description | Default |
|----------|-------------|---------|
| `OUTAGE_REGION_ID` | Yasno region ID (e.g. `25` for Kyiv) | — |
| `OUTAGE_DSO_ID` | Yasno DSO ID (e.g. `902` for DTEK Kyiv) | — |

### Telegram Bot (optional)

| Variable | Description | Default |
|----------|-------------|---------|
| `TELEGRAM_ENABLED` | Enable the Telegram bot (`true` / `false`) | `false` |
| `TELEGRAM_BOT_TOKEN` | Bot token from [@BotFather](https://t.me/BotFather) | — |
| `TELEGRAM_ALLOWED_USERS` | Comma-separated list of allowed Telegram user IDs | — |

**How to set up:**

1. Message [@BotFather](https://t.me/BotFather) on Telegram and create a new bot with `/newbot`
2. Copy the bot token into `TELEGRAM_BOT_TOKEN`
3. Find your Telegram user ID (see below), add it to `TELEGRAM_ALLOWED_USERS`
4. Set `TELEGRAM_ENABLED=true` and restart the dashboard

**How to find your Telegram user ID:**

There are two ways:

- **Using this bot** — set `TELEGRAM_ENABLED=true` with your bot token and leave `TELEGRAM_ALLOWED_USERS` empty for now. Start the dashboard, then open your bot in Telegram and send `/start`. The bot will reply with your numeric user ID (e.g. `123456789`). Add it to `TELEGRAM_ALLOWED_USERS` and restart.
- **Using @userinfobot** — search for `@userinfobot` in Telegram, start it, and it will immediately reply with your user ID.

For multiple users, separate IDs with commas: `TELEGRAM_ALLOWED_USERS=123456789,987654321`

**Bot commands:**

| Command | Description |
|---------|-------------|
| `/start` | Shows your Telegram user ID and authorization status |
| `/battery` | Current battery SOC, voltage, power, and estimated time remaining |
| `/outage` | Next scheduled power outage window and countdown |
| `/grid` | Daily grid consumption report (import/export) |
| `/test` | Sends sample battery and grid messages |

The bot also provides a keyboard with Ukrainian-labeled buttons for quick access. Messages include weather-themed Ukrainian poetry excerpts.

### Data Files (optional)

| Variable | Description | Default |
|----------|-------------|---------|
| `OUTAGE_HISTORY_FILE` | Path to outage history JSON file | `outage_history.json` |
| `PHASE_STATS_FILE` | Path to phase statistics JSON file | `phase_stats.json` |
| `PHASE_HISTORY_FILE` | Path to phase history JSON file | `phase_history.json` |

### Deployment (used by `deploy.sh`)

| Variable | Description | Example |
|----------|-------------|---------|
| `DEPLOY_HOST` | Remote server IP or hostname | `192.168.1.50` |
| `DEPLOY_USER` | SSH user on the remote server | `pi` |
| `DEPLOY_DIR` | Installation directory on the remote server | `/home/pi/deye-dashboard` |
| `DEPLOY_SERVICE_NAME` | Systemd service name | `deye-dashboard` |

## Local Development

Use `deploy_local.sh` to run the dashboard locally with the Telegram bot disabled:

```bash
chmod +x deploy_local.sh
./deploy_local.sh
```

This sources your `.env`, overrides `TELEGRAM_ENABLED=false`, activates the virtual environment, and starts the app. Useful for UI development without triggering bot messages.

You need a `.env` file with at least `INVERTER_IP` and `LOGGER_SERIAL` set. Either create one manually from `.env.example` or run `./deploy.sh` once to generate it interactively.

## Deploying to a Remote Server

`deploy.sh` deploys the dashboard to a remote Linux server over SSH and sets it up as a systemd service. The remote server needs Python 3.7+, SSH access, and `sudo` for systemd management.

### Prerequisites

- SSH key-based access to the remote server (the script runs `ssh` and `rsync` non-interactively)
- `sudo` privileges on the remote server (for systemd service setup)
- Python 3.7+ installed on the remote server

### First-time deploy

If no `.env` file exists, the script runs an interactive setup wizard:

```bash
chmod +x deploy.sh
./deploy.sh
```

The wizard prompts for all settings in order:

1. **Inverter** — IP address and logger serial number
2. **Deployment** — remote host, SSH user, install directory, service name
3. **Weather** — latitude and longitude for forecast (defaults to Kyiv)
4. **Outage schedule** — provider selection (Lvivoblenergo, Yasno, or none) with provider-specific follow-up questions
5. **Telegram** — enable/disable, bot token, and allowed user IDs

After answering all prompts, the script:
- Writes the `.env` file
- Prints a summary of all settings
- Asks for confirmation before deploying

If you decline, the `.env` is kept so you can edit it and re-run `./deploy.sh`.

### Subsequent deploys

When `.env` already exists, the script skips all prompts and deploys immediately:

```bash
./deploy.sh
```

To change settings, edit `.env` directly and re-deploy.

### What the deploy script does

1. **Rsync** — copies `app.py`, `inverter.py`, `telegram_bot.py`, `poems.py`, `outage_providers/`, `requirements.txt`, `templates/`, and `.env` to the remote server
2. **Python setup** — creates a virtual environment (if needed) and installs dependencies from `requirements.txt`
3. **Systemd service** — creates a service file at `/etc/systemd/system/<service-name>.service`, enables it, and restarts it
4. The dashboard runs on port 8080 by default

### Managing the remote service

```bash
# Check status
ssh user@host 'sudo systemctl status deye-dashboard'

# View live logs
ssh user@host 'sudo journalctl -u deye-dashboard -f'

# Restart after config changes
ssh user@host 'sudo systemctl restart deye-dashboard'

# Stop the service
ssh user@host 'sudo systemctl stop deye-dashboard'
```

## Finding Your Inverter Details

### Inverter IP

Check your router's connected devices list or scan your network:

```bash
nmap -sP 192.168.1.0/24
```

### Logger Serial Number

The serial number is printed on the Solarman Wi-Fi logger stick, or can be found in the Solarman app under device settings.

## Utility Scripts

```bash
# Test inverter connection
python test_connection.py

# Scan for battery voltage register
python scan_battery.py

# Scan for phase-related registers
python scan_phases.py

# Scan all available registers
python scan_registers.py
```

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/data` | GET | Current inverter readings |
| `/api/weather` | GET | Current weather and forecast |
| `/api/outage_schedule` | GET | Upcoming outage windows |
| `/api/phase-stats` | GET | Daily phase statistics |
| `/api/phase-history` | GET | Phase power history |
| `/api/outages` | GET | Outage history |
| `/api/outages` | POST | Record outage event |
| `/api/outages/clear` | POST | Clear outage history |
| `/api/phase-stats/clear` | POST | Clear phase statistics |

## License

MIT License
