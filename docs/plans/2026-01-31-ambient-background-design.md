# Ambient Weather Background Design

## Goal
Make the dashboard background dynamically reflect real weather conditions, time of day, and system state (battery + grid). Designed for a wall-mounted iPad as an ambient display.

## Data Source
- **Open-Meteo API** (free, no API key)
- Coordinates: `49.7837, 24.0391`
- Data: current temperature, WMO weather code, sunrise/sunset times
- Cached in memory on the backend, refreshed every 15 minutes via background thread

## Backend Changes (`app.py`)

### Weather fetcher
- Global dict `weather_cache = {}` stores latest weather data
- Background thread calls Open-Meteo every 15 minutes:
  ```
  https://api.open-meteo.com/v1/forecast?latitude=49.7837&longitude=24.0391&current=temperature_2m,weather_code&daily=sunrise,sunset&timezone=auto&forecast_days=1
  ```
- On failure, keeps serving last successful response
- New endpoint: `GET /api/weather` returns cached dict:
  ```json
  {
    "temperature": -3.2,
    "weather_code": 71,
    "sunrise": "07:45",
    "sunset": "17:12",
    "last_updated": "2026-01-31T14:30:00"
  }
  ```

## Frontend Changes (`templates/index.html`)

### Architecture
- `<canvas id="bg-canvas">` positioned behind all content (fixed, full viewport, z-index: -1)
- Body gradient set via inline style with smooth CSS transition (3s ease)
- `requestAnimationFrame` loop drives particle rendering on canvas
- `updateBackground()` called on each dashboard refresh (every 5s), reads weather + inverter data

### Visual Priority (highest wins)
1. **Grid offline + battery < 50%** — red tint overlay, particles fade out
2. **Weather + time of day** — normal ambient visuals (used when grid is online OR battery >= 50%)

### Visual Modes

#### Clear Day (sunny, solar generating)
- Gradient: warm blue sky (`#1a3a5c` → `#2d6a9f`) with golden tint
- Particles: 5-8 slow-drifting sun ray lines, semi-transparent gold, diagonal

#### Clear Night
- Gradient: deep navy to dark purple (`#0a0a1a` → `#12122e`)
- Particles: 30-50 tiny stars, white dots fading in/out randomly (1-4s cycles), varying brightness

#### Cloudy / Overcast
- Gradient: muted grey-blue (`#1a2030` → `#2a3040`)
- Particles: 3-5 very slow horizontal grey wisps

#### Snow (weather code = snow OR temp < 0°C)
- Gradient: icy blue-white (`#1a2535` → `#2a3a4f`)
- Particles: 20-30 snowflakes, 2-5px, diagonal drift with wobble

#### Rain
- Gradient: dark blue-grey (`#151d28` → `#1e2a38`)
- Particles: 30-40 thin vertical lines (1px × 8-15px), fast falling

#### Dawn/Dusk (within 45 min of sunrise/sunset)
- Gradient blends orange-pink tones (`#2d1a1a` → `#1a2a3a`) into day/night palette
- Particles: weather-driven, slightly warmer tint

### Battery Override (Grid Offline + SOC < 50%)
- Red overlay: `rgba(80, 15, 15, opacity)` where `opacity = min((50 - soc) / 50, 0.5)`
- At 50% SOC: invisible. At 0% SOC: 0.5 opacity max (not aggressive)
- Particle count reduces proportionally: 50% = full, 25% = half, 10% = nearly gone
- Remaining particles slow down slightly
- Grid restore: red fades out over 2-3s, particles gradually restore

### Transitions
- All gradient changes: `transition: background 3s ease`
- Mode changes: old particles fade out (2s opacity reduction), new particles fade in
- Dawn/dusk: continuous interpolation, not a sudden switch

### WMO Weather Codes Reference
| Code | Condition | Visual Mode |
|------|-----------|-------------|
| 0 | Clear sky | Clear Day/Night |
| 1-3 | Partly cloudy to overcast | Cloudy |
| 45, 48 | Fog | Cloudy (dimmer) |
| 51-57 | Drizzle | Rain (fewer particles) |
| 61-67 | Rain | Rain |
| 71-77 | Snow | Snow |
| 80-82 | Rain showers | Rain |
| 85-86 | Snow showers | Snow |
| 95-99 | Thunderstorm | Rain (with occasional bright flash) |

## Files Modified
- `app.py` — weather cache, background thread, `/api/weather` endpoint
- `templates/index.html` — canvas element, particle system JS, gradient logic, CSS transitions
