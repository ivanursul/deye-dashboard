"""Telegram bot for Deye solar inverter monitoring notifications."""
import json
import os
import time
import logging
import threading
from datetime import datetime, date
from calendar import monthrange
import requests

from outage_providers import BATTERY_CAPACITY_KWH
try:
    from poems import get_poem
except ImportError:
    get_poem = None

logger = logging.getLogger(__name__)

# 1800s literary Ukrainian style messages
MESSAGES_BATTERY_LOW = [
    "Шановне панство! Сповіщаю з превеликим жалем, що батерія наша знесилена — "
    "лишилось їй сили на <b>{soc}%</b>. Як козак без шаблі, так і хата без струму — біда, та й годі!",

    "Вельмишановні добродії! Батерія наша, мов чумак у степу безводному, "
    "ледве животіє — заряду лишилось <b>{soc}%</b>. Готуйте свічки та лучину, бо темрява надходить!",

    "Панове та паніматки! Маю честь доповісти, що батерія наша зовсім "
    "захиріла — <b>{soc}%</b> і то ледь дише. Як казав мій дід: без сили нема й долі!",
]

MESSAGES_GRID_RESTORED = [
    "Радійте, люди добрі! Електрика, мов блудний син, повернулася до нашої оселі! "
    "Знову тече струм по дротах, як мед по вусах — хвала небесам і обленерго!",

    "Ура, панове! Струм повернувся, наче козак із походу — з перемогою! "
    "Обленерго змилувалось над нами грішними. Вмикайте самовари та електричні машини!",

    "Слава! Слава! Тричі слава! Електрика знов освітила наші палати! "
    "Годі вже при свічках куняти — цивілізація повернулась до нашого маєтку!",
]

MESSAGES_TEST_BATTERY = (
    "[ ТЕСТ ] Шановне панство! Це є випробування сповіщення про батерію. "
    "Уявіть собі: батерія наша, мов старий дідуган, "
    "ледве тримається на ногах — заряду їй лишилось аж 15%! "
    "Як казав славетний Котляревський: «Еней був парубок моторний» — "
    "а наша батерія вже ні!"
)

MESSAGES_TEST_GRID = (
    "[ ТЕСТ ] Гей, панове-товариство! Це є випробування сповіщення про електрику. "
    "Уявіть: струм повернувся! Мов Прометей вогонь людям приніс, "
    "так і обленерго нам знову електрику подало! "
    "Припиніть голосити та ховати сало — світло є!"
)

# --- Outage schedule messages ---

MESSAGES_OUTAGE_ACTIVE = [
    "Терпіння, добродію! За графіком Львівобленерго, світло має повернутись о <b>{end_time}</b>. "
    "Лишилось чекати <b>{remaining}</b>. Як казав Шевченко: «Борітеся — поборете!»",

    "Тримайтесь, панове! Темрява панує, але не вічно — о <b>{end_time}</b> має бути світло. "
    "Ще <b>{remaining}</b> і знову заживемо як люди! Козак терпів і нам велів!",

    "Не журіться, шановне панство! Обленерго обіцяє повернути струм о <b>{end_time}</b>. "
    "Лишилось <b>{remaining}</b>. Як то кажуть: ніч найтемніша перед світанком!",
]

MESSAGES_UPCOMING_BATTERY_OK = [
    "Світло є, панове! За графіком темрява прийде з <b>{start_time}</b> до <b>{end_time}</b>. "
    "Але не журіться — батерія наша на <b>{soc}%</b>, як добрий козак при повній зброї. "
    "Вистачить з лишком!",

    "Струм тече, хвала небесам! Відключення заплановано з <b>{start_time}</b> до <b>{end_time}</b>. "
    "Батерія на <b>{soc}%</b> — це як повний льох перед зимою. Переживемо!",

    "Електрика є, панове-товариство! Обленерго планує темряву з <b>{start_time}</b> до <b>{end_time}</b>. "
    "Але батерія на <b>{soc}%</b> — це нам як козакові шабля при боці. Нічого не страшно!",
]

MESSAGES_UPCOMING_BATTERY_TIGHT = [
    "Світло є, але обережно! Темрява прийде з <b>{start_time}</b> до <b>{end_time}</b>, "
    "а батерія лише на <b>{soc}%</b>. При теперішньому споживанні (<b>{load}W</b>) може не дотягнути. "
    "Вимикайте зайве, панове!",

    "Струм поки є, але хмари збираються! З <b>{start_time}</b> до <b>{end_time}</b> — відключення. "
    "Батерія на <b>{soc}%</b>, а споживання <b>{load}W</b> — на межі. "
    "Як казав мій дід: «Бережи сало смолоду!»",

    "Електрика є, та не розслабляйтесь! З <b>{start_time}</b> до <b>{end_time}</b> буде темно. "
    "Батерія на <b>{soc}%</b> при споживанні <b>{load}W</b> — це як йти в дорогу з малою торбою. "
    "Зменшіть апетити, добродії!",
]

MESSAGES_UPCOMING_BATTERY_LOW = [
    "Світло є, але біда на порозі! З <b>{start_time}</b> до <b>{end_time}</b> — відключення, "
    "а батерія на жалюгідних <b>{soc}%</b>. При споживанні <b>{load}W</b> це як йти в бій "
    "з порожніми кишенями!",

    "Струм поки тече, але лихо чекає! З <b>{start_time}</b> до <b>{end_time}</b> обленерго вимкне світло. "
    "Батерія лише на <b>{soc}%</b>, а споживання <b>{load}W</b> — не вистачить, хоч плач! "
    "Готуйте свічки та лучину!",

    "Електрика є, та ненадовго! З <b>{start_time}</b> до <b>{end_time}</b> прийде темрява. "
    "Батерія на <b>{soc}%</b> при <b>{load}W</b> — це як чумак без волів у степу. "
    "Будьте готові до найгіршого, панове!",
]

MESSAGES_OUTAGE_CLEAR = [
    "Радійте, панове! Сьогодні Львівобленерго милостиве — жодних відключень "
    "для нашої групи! Живемо як пани!",

    "Слава! Сьогодні обленерго дарує нам спокій — жодних відключень! "
    "Користуйтесь електрикою на повну, як пан у своєму маєтку!",

    "Гарна новина, добродії! Сьогодні графік відключень нас оминає! "
    "Можна жити спокійно, як за гетьмана Мазепи у мирні часи!",
]

MESSAGES_GRID_DOWN = [
    "Панове, світло зникло! {schedule_info} "
    "Батерія на <b>{soc}%</b> — {battery_verdict}",

    "Увага, добродії! Електрику вимкнули! {schedule_info} "
    "Батерія наша на <b>{soc}%</b> — {battery_verdict}",

    "Біда, панове-товариство! Струм пропав! {schedule_info} "
    "Заряд батареї <b>{soc}%</b> — {battery_verdict}",
]

MESSAGES_OUTAGE_UNKNOWN = [
    "Перепрошую, добродію! Не вдалося дізнатись графік відключень — "
    "зв'язок із Львівобленерго загубився, як лист у бурю. "
    "Перевірте на poweron.loe.lviv.ua самостійно.",

    "Вибачайте, панове! Графік відключень недоступний — "
    "мабуть, і в обленерго світло вимкнули! "
    "Спробуйте пізніше або гляньте на poweron.loe.lviv.ua.",
]


BATTERY_REPORT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "battery_reports")


class TelegramBot:
    def __init__(self, token, allowed_users, inverter, battery_sampler=None,
                 outage_poller=None, state_file=None, grid_daily_log_file=None,
                 weather_poller=None):
        self.token = token
        self.allowed_users = set(allowed_users)
        self.inverter = inverter
        self.battery_sampler = battery_sampler
        self.outage_poller = outage_poller
        self.grid_daily_log_file = grid_daily_log_file
        self.weather_poller = weather_poller
        self.api_url = f"https://api.telegram.org/bot{token}"
        self.last_update_id = 0
        self.message_index = 0

        # Monitoring state
        self.battery_low_notified = False
        self.grid_down_since = None
        self.grid_up_since = None
        self.grid_confirmed_down = False

        self._running = False
        self._thread = None
        self.state_file = state_file
        self._load_state()

    def _load_state(self):
        """Load monitoring state from file if available."""
        if not self.state_file or not os.path.exists(self.state_file):
            return
        try:
            with open(self.state_file, "r") as f:
                state = json.load(f)
            self.grid_confirmed_down = state.get("grid_confirmed_down", False)
            self.battery_low_notified = state.get("battery_low_notified", False)
            self.grid_down_since = state.get("grid_down_since")
            self.grid_up_since = state.get("grid_up_since")
            self.last_update_id = state.get("last_update_id", 0)
            logger.info("Loaded bot state from %s", self.state_file)
        except Exception:
            logger.exception("Failed to load bot state from %s, using defaults", self.state_file)

    def _save_state(self):
        """Persist monitoring state to file."""
        if not self.state_file:
            return
        state = {
            "grid_confirmed_down": self.grid_confirmed_down,
            "battery_low_notified": self.battery_low_notified,
            "grid_down_since": self.grid_down_since,
            "grid_up_since": self.grid_up_since,
            "last_update_id": self.last_update_id,
        }
        try:
            with open(self.state_file, "w") as f:
                json.dump(state, f, indent=2)
        except Exception:
            logger.exception("Failed to save bot state to %s", self.state_file)

    def _save_battery_report(self, data, trigger):
        """Save a debug report file with all inverter data when a battery report is sent."""
        os.makedirs(BATTERY_REPORT_DIR, exist_ok=True)
        ts = datetime.now()
        filename = ts.strftime(f"%Y-%m-%d_%H-%M-%S_{trigger}.json")
        filepath = os.path.join(BATTERY_REPORT_DIR, filename)
        report = {
            "timestamp": ts.isoformat(),
            "trigger": trigger,
            "inverter_data": data,
        }
        if self.battery_sampler:
            report["sampler_voltage"] = self.battery_sampler.get_voltage()
            report["sampler_soc"] = self.battery_sampler.get_soc()
            with self.battery_sampler._lock:
                report["sampler_buffer"] = list(self.battery_sampler._buffer)
        try:
            with open(filepath, "w") as f:
                json.dump(report, f, indent=2, default=str)
            logger.info("Battery report saved to %s", filepath)
        except Exception:
            logger.exception("Failed to save battery report to %s", filepath)

    def _pick_message(self, messages, **kwargs):
        """Pick next message from rotation and format it."""
        msg = messages[self.message_index % len(messages)]
        self.message_index += 1
        return msg.format(**kwargs)

    def _format_poem(self):
        """Get a formatted poem based on current weather data."""
        if get_poem is None:
            return ""
        weather_code = None
        sunrise = None
        sunset = None
        if self.weather_poller:
            data = self.weather_poller.data
            if data:
                weather_code = data.get("weather_code")
                sunrise = data.get("sunrise")
                sunset = data.get("sunset")
        return get_poem(weather_code, sunrise, sunset)

    def _append_poem(self, msg):
        """Append a poem to a message string."""
        poem = self._format_poem()
        if poem:
            return msg + "\n\n" + poem
        return msg

    def send_message(self, chat_id, text, reply_markup=None):
        """Send a message to a specific chat with exponential backoff retry."""
        payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
        if reply_markup:
            payload["reply_markup"] = reply_markup

        for attempt in range(4):  # up to 4 attempts: 0s, 2s, 4s, 8s
            try:
                resp = requests.post(
                    f"{self.api_url}/sendMessage",
                    json=payload,
                    timeout=10,
                )
                if resp.ok:
                    return True
                logger.error("Failed to send message (attempt %d): %s", attempt + 1, resp.text)
            except Exception:
                logger.warning("Error sending Telegram message (attempt %d)", attempt + 1)
            if attempt < 3:
                time.sleep(2 ** attempt)

        logger.error("Failed to send message after 4 attempts to chat %s", chat_id)
        return False

    def broadcast(self, text):
        """Send a message to all allowed users."""
        for user_id in self.allowed_users:
            self.send_message(user_id, text)

    def poll_commands(self):
        """Check for incoming bot commands with backoff retry."""
        updates = None
        for attempt in range(3):  # up to 3 attempts: 0s, 2s, 4s
            try:
                resp = requests.get(
                    f"{self.api_url}/getUpdates",
                    params={"offset": self.last_update_id + 1, "timeout": 0},
                    timeout=10,
                )
                if resp.ok:
                    updates = resp.json().get("result", [])
                    self._poll_failures = 0
                    break
                logger.warning("Telegram getUpdates failed (attempt %d): %s", attempt + 1, resp.status_code)
            except Exception:
                logger.warning("Error polling Telegram updates (attempt %d)", attempt + 1)
            if attempt < 2:
                time.sleep(2 ** attempt)

        if updates is None:
            self._poll_failures = getattr(self, '_poll_failures', 0) + 1
            return

        for update in updates:
            self.last_update_id = update["update_id"]
            message = update.get("message")
            if not message or not message.get("text"):
                continue

            chat_id = message["chat"]["id"]
            user_id = message["from"]["id"]
            text = message["text"].strip()

            if text == "/start":
                self._handle_start(chat_id, user_id)
            elif text == "/test":
                self._handle_test(chat_id, user_id)
            elif text in ("/battery", "⚡ Сховище енергії"):
                self._handle_battery(chat_id, user_id)
            elif text in ("/outage", "💡 Коли включать світло?"):
                self._handle_outage(chat_id, user_id)
            elif text in ("/grid", "📊 Спожито з мережі"):
                self._handle_grid_consumption(chat_id, user_id)

    def _main_keyboard(self):
        """Return the persistent reply keyboard."""
        return {
            "keyboard": [
                [{"text": "⚡ Сховище енергії"}],
                [{"text": "💡 Коли включать світло?"}],
                [{"text": "📊 Спожито з мережі"}],
            ],
            "resize_keyboard": True,
        }

    def _handle_start(self, chat_id, user_id):
        """Handle /start command."""
        if user_id in self.allowed_users:
            msg = (
                f"Вітаю, добродію! Ваш Telegram ID: {user_id}\n"
                f"Ви у списку дозволених. Сповіщення увімкнено."
            )
            self.send_message(
                chat_id,
                self._append_poem(msg),
                reply_markup=self._main_keyboard(),
            )
        else:
            self.send_message(
                chat_id,
                f"Ваш Telegram ID: {user_id}\n"
                f"Додайте цей ID до змінної TELEGRAM_ALLOWED_USERS щоб отримувати сповіщення.",
            )

    def _handle_test(self, chat_id, user_id):
        """Handle /test command — send both sample messages."""
        if user_id not in self.allowed_users:
            self.send_message(chat_id, f"Ваш ID ({user_id}) не у списку дозволених.")
            return

        self.send_message(chat_id, self._append_poem(MESSAGES_TEST_BATTERY))
        self.send_message(chat_id, self._append_poem(MESSAGES_TEST_GRID))

    def _handle_battery(self, chat_id, user_id):
        """Handle battery status request."""
        if user_id not in self.allowed_users:
            self.send_message(chat_id, f"Ваш ID ({user_id}) не у списку дозволених.")
            return

        if not self.inverter.config.has_battery:
            self.send_message(chat_id, "Батарею не налаштовано для цього інвертора.")
            return

        try:
            data = self.inverter.read_all_data(battery_sampler=self.battery_sampler)
        except Exception:
            self.send_message(chat_id, "Не вдалося зчитати дані з інвертора.")
            return

        if data.get("error"):
            self.send_message(chat_id, "Не вдалося зчитати дані з інвертора.")
            return

        self._save_battery_report(data, "user_request")

        soc = data.get("battery_soc", 0)
        voltage = data.get("battery_voltage", 0)
        power = data.get("battery_power", 0)
        status = data.get("battery_status", "Невідомо")

        if soc >= 80:
            mood = "Батерія наша повна сил, мов козак після відпочинку! 💪"
        elif soc >= 50:
            mood = "Батерія тримається молодцем, ще повоює! ⚡"
        elif soc >= 30:
            mood = "Батерія починає втомлюватись, варто придивитись... 👀"
        else:
            mood = "Батерія ледве дише, як чумак у пустелі! 🫠"

        msg = (
            f"🔋 Заряд: <b>{soc}%</b>\n"
            f"⚡ Напруга: <b>{voltage:.1f}V</b>\n"
            f"🔌 Потужність: <b>{power}W</b>\n"
            f"📊 Стан: {status}\n\n"
            f"{mood}"
        )
        self.send_message(chat_id, self._append_poem(msg))

    def _handle_outage(self, chat_id, user_id):
        """Handle outage schedule request."""
        if user_id not in self.allowed_users:
            self.send_message(chat_id, f"Ваш ID ({user_id}) не у списку дозволених.")
            return

        if not self.outage_poller:
            self.send_message(chat_id, "Моніторинг графіку відключень не налаштовано.")
            return

        status = self.outage_poller.get_outage_status()

        if status["status"] == "active":
            end_time = status["end_time"].strftime("%H:%M")
            remaining_min = status["remaining_minutes"]
            hours = remaining_min // 60
            mins = remaining_min % 60
            if hours > 0:
                remaining = f"{hours} год {mins} хв"
            else:
                remaining = f"{mins} хв"
            msg = self._pick_message(
                MESSAGES_OUTAGE_ACTIVE, end_time=end_time, remaining=remaining,
            )

        elif status["status"] == "upcoming":
            windows = status["upcoming_windows"]
            start_dt, end_dt = windows[0]
            start_time = start_dt.strftime("%H:%M")
            end_time = end_dt.strftime("%H:%M")
            outage_hours = (end_dt - start_dt).total_seconds() / 3600

            # Get battery and load data for survival estimate
            soc = 0
            load = 0
            if self.inverter.config.has_battery:
                try:
                    data = self.inverter.read_all_data(
                        battery_sampler=self.battery_sampler
                    )
                    if not data.get("error"):
                        soc = data.get("battery_soc", 0)
                        load = data.get("load_power", 0)
                except Exception:
                    pass

            if not self.inverter.config.has_battery:
                msg = (
                    f"Увага! Відключення заплановано з <b>{start_time}</b> "
                    f"до <b>{end_time}</b>. Батареї немає — чекаємо на мережу."
                )
            else:
                available_kwh = BATTERY_CAPACITY_KWH * (soc / 100)
                needed_kwh = (load / 1000) * outage_hours

                if needed_kwh <= 0 or available_kwh >= needed_kwh * 1.1:
                    msg = self._pick_message(
                        MESSAGES_UPCOMING_BATTERY_OK,
                        start_time=start_time, end_time=end_time, soc=soc,
                    )
                elif available_kwh >= needed_kwh * 0.7:
                    msg = self._pick_message(
                        MESSAGES_UPCOMING_BATTERY_TIGHT,
                        start_time=start_time, end_time=end_time,
                        soc=soc, load=load,
                    )
                else:
                    msg = self._pick_message(
                        MESSAGES_UPCOMING_BATTERY_LOW,
                        start_time=start_time, end_time=end_time,
                        soc=soc, load=load,
                    )

            # If there are more windows today, append them
            if len(windows) > 1:
                extra = ", ".join(
                    f"з {s.strftime('%H:%M')} до {e.strftime('%H:%M')}"
                    for s, e in windows[1:]
                )
                msg += f"\n\nТакож заплановано: {extra}"

        elif status["status"] == "clear":
            msg = self._pick_message(MESSAGES_OUTAGE_CLEAR)

        else:
            msg = self._pick_message(MESSAGES_OUTAGE_UNKNOWN)

        self.send_message(chat_id, self._append_poem(msg))

    def _load_grid_daily_log(self):
        """Load grid daily import log from file."""
        if not self.grid_daily_log_file or not os.path.exists(self.grid_daily_log_file):
            return {}
        try:
            with open(self.grid_daily_log_file, "r") as f:
                return json.load(f)
        except Exception:
            logger.exception("Failed to load grid daily log")
            return {}

    def _sum_month(self, log, year, month):
        """Sum daily grid import values for a given year/month. Returns (total_kwh, days_covered, first_day, last_day)."""
        prefix = f"{year:04d}-{month:02d}-"
        days = []
        total = 0.0
        for day_str, kwh in log.items():
            if day_str.startswith(prefix):
                days.append(day_str)
                total += kwh
        if not days:
            return 0.0, 0, None, None
        days.sort()
        return total, len(days), days[0], days[-1]

    def _handle_grid_consumption(self, chat_id, user_id):
        """Handle grid consumption request — show monthly totals."""
        if user_id not in self.allowed_users:
            self.send_message(chat_id, f"Ваш ID ({user_id}) не у списку дозволених.")
            return

        log = self._load_grid_daily_log()
        if not log:
            self.send_message(
                chat_id,
                "Поки що немає даних про споживання з мережі. "
                "Дані почнуть збиратися автоматично.",
            )
            return

        MONTH_NAMES = {
            1: "Січень", 2: "Лютий", 3: "Березень", 4: "Квітень",
            5: "Травень", 6: "Червень", 7: "Липень", 8: "Серпень",
            9: "Вересень", 10: "Жовтень", 11: "Листопад", 12: "Грудень",
        }
        MONTH_NAMES_GEN = {
            1: "січня", 2: "лютого", 3: "березня", 4: "квітня",
            5: "травня", 6: "червня", 7: "липня", 8: "серпня",
            9: "вересня", 10: "жовтня", 11: "листопада", 12: "грудня",
        }

        today = date.today()
        cur_year, cur_month = today.year, today.month

        # Previous month
        if cur_month == 1:
            prev_year, prev_month = cur_year - 1, 12
        else:
            prev_year, prev_month = cur_year, cur_month - 1

        cur_total, cur_days, cur_first, cur_last = self._sum_month(log, cur_year, cur_month)
        prev_total, prev_days, prev_first, prev_last = self._sum_month(log, prev_year, prev_month)

        lines = ["📊 Споживання з мережі\n"]

        # Current month
        month_name = MONTH_NAMES[cur_month]
        if cur_days > 0:
            first_day = int(cur_first.split("-")[2])
            last_day = int(cur_last.split("-")[2])
            gen_name = MONTH_NAMES_GEN[cur_month]
            lines.append(f"{month_name} {cur_year} (поточний):")
            lines.append(f"<b>{cur_total:.1f} кВт·год</b> ({first_day}-{last_day} {gen_name})")
        else:
            lines.append(f"{month_name} {cur_year} (поточний):")
            lines.append("Ще немає даних")

        lines.append("")

        # Previous month
        prev_name = MONTH_NAMES[prev_month]
        if prev_days > 0:
            _, max_day = monthrange(prev_year, prev_month)
            if prev_days >= max_day - 1:
                lines.append(f"{prev_name} {prev_year}:")
                lines.append(f"<b>{prev_total:.1f} кВт·год</b>")
            else:
                first_day = int(prev_first.split("-")[2])
                last_day = int(prev_last.split("-")[2])
                gen_name = MONTH_NAMES_GEN[prev_month]
                lines.append(f"{prev_name} {prev_year} (неповний):")
                lines.append(f"<b>{prev_total:.1f} кВт·год</b> ({first_day}-{last_day} {gen_name})")
        else:
            lines.append(f"{prev_name} {prev_year}:")
            lines.append("Немає даних")

        self.send_message(chat_id, self._append_poem("\n".join(lines)))

    def _broadcast_grid_down(self, soc):
        """Broadcast grid-down notification with schedule and battery info."""
        # Get schedule info
        schedule_info = ""
        if self.outage_poller:
            status = self.outage_poller.get_outage_status()
            if status["status"] == "active":
                end_time = status["end_time"].strftime("%H:%M")
                remaining_min = status["remaining_minutes"]
                hours = remaining_min // 60
                mins = remaining_min % 60
                if hours > 0:
                    remaining = f"{hours} год {mins} хв"
                else:
                    remaining = f"{mins} хв"
                schedule_info = (
                    f"За графіком Львівобленерго, світло має повернутись о <b>{end_time}</b> "
                    f"(ще <b>{remaining}</b>)."
                )
            else:
                schedule_info = (
                    "Цього відключення немає у графіку Львівобленерго — "
                    "можливо, аварійне."
                )
        else:
            schedule_info = "Графік відключень недоступний."

        # Battery verdict
        if not self.inverter.config.has_battery:
            battery_verdict = "батареї немає, чекаємо на мережу."
        elif soc >= 70:
            battery_verdict = "тримаємось як козаки, вистачить надовго!"
        elif soc >= 40:
            battery_verdict = "протримаємось, але без зайвого марнотратства."
        elif soc >= 20:
            battery_verdict = "маловато буде, панове. Економте!"
        else:
            battery_verdict = "зовсім кепсько, готуйте свічки!"

        msg = self._pick_message(
            MESSAGES_GRID_DOWN,
            schedule_info=schedule_info, soc=soc, battery_verdict=battery_verdict,
        )
        self.broadcast(self._append_poem(msg))

    def check_inverter(self):
        """Read inverter data and check alert conditions."""
        try:
            data = self.inverter.read_all_data(battery_sampler=self.battery_sampler)
        except Exception:
            logger.exception("Error reading inverter data for Telegram bot")
            return

        if "error" in data and data["error"]:
            return

        grid_voltage = data.get("grid_voltage", 230)
        has_battery = self.inverter.config.has_battery
        now = time.time()

        # --- Battery monitoring ---
        if has_battery:
            soc = data.get("battery_soc", 100)
            battery_voltage = data.get("battery_voltage", 0)

            # Sanity check: if battery voltage reads as 0 or near-0, the inverter
            # returned a glitched value. Skip this reading to avoid false alerts.
            if battery_voltage < 10:
                logger.warning(
                    "Skipping inverter check: battery voltage %.1fV looks like a glitch (SOC=%s%%)",
                    battery_voltage, soc,
                )
                return

            if soc < 30 and not self.battery_low_notified:
                self._save_battery_report(data, "battery_low_alert")
                msg = self._pick_message(MESSAGES_BATTERY_LOW, soc=soc)
                self.broadcast(self._append_poem(msg))
                self.battery_low_notified = True
                logger.info("Battery low notification sent (SOC=%s%%)", soc)
            elif soc >= 30 and self.battery_low_notified:
                self.battery_low_notified = False

        # --- Grid monitoring with 2-minute debounce ---
        grid_is_down = grid_voltage < 50
        soc_for_grid = data.get("battery_soc", 0) if has_battery else 0

        if grid_is_down:
            self.grid_up_since = None
            if self.grid_down_since is None:
                self.grid_down_since = now
            elif not self.grid_confirmed_down and (now - self.grid_down_since) >= 120:
                self.grid_confirmed_down = True
                self._broadcast_grid_down(soc_for_grid)
                logger.info("Grid confirmed down (voltage=%.1fV)", grid_voltage)
        else:
            self.grid_down_since = None
            if self.grid_confirmed_down:
                if self.grid_up_since is None:
                    self.grid_up_since = now
                elif (now - self.grid_up_since) >= 60:
                    msg = self._pick_message(MESSAGES_GRID_RESTORED)
                    self.broadcast(self._append_poem(msg))
                    self.grid_confirmed_down = False
                    self.grid_up_since = None
                    logger.info("Grid restored notification sent (voltage=%.1fV)", grid_voltage)

    def run(self, inverter_interval=120, command_interval=5):
        """Main loop: poll commands frequently, check inverter less often."""
        self._running = True
        self._poll_failures = 0
        logger.info(
            "Telegram bot started (commands every %ds, inverter every %ds)",
            command_interval, inverter_interval,
        )
        last_inverter_check = 0
        last_poll = 0

        while self._running:
            now = time.time()

            # Back off polling when Telegram API is unreachable
            # Normal: every command_interval. After failures: up to 60s
            poll_backoff = min(command_interval * (2 ** self._poll_failures), 60)
            if now - last_poll >= poll_backoff:
                self.poll_commands()
                self._save_state()
                last_poll = now

            if now - last_inverter_check >= inverter_interval:
                self.check_inverter()
                self._save_state()
                last_inverter_check = now

            time.sleep(1)

    def start(self, inverter_interval=120):
        """Start the bot in a background thread."""
        self._thread = threading.Thread(
            target=self.run, args=(inverter_interval,), daemon=True
        )
        self._thread.start()
        return self._thread

    def stop(self):
        """Stop the bot."""
        self._running = False
