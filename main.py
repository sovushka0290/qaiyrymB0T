import asyncio
import json
import logging
import math
import os
import re
import sys
from typing import Dict, Any, List
import requests
from typing import Dict, Any, List, Optional
from datetime import datetime

import gspread
from google.oauth2.service_account import Credentials
from google import genai
from google.genai import types
from aiogram import Bot, Dispatcher, F, Router, html
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart, StateFilter, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    WebAppInfo,
)
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO, stream=sys.stdout)
logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════════════
# КОНФИГУРАЦИЯ
# ═══════════════════════════════════════════════════════════════════════════

BOT_TOKEN = os.getenv("BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
ADMIN_ID = os.getenv("ADMIN_ID", "")
WEBAPP_URL = os.getenv("WEBAPP_URL", "")
APPS_SCRIPT_URL = os.getenv("APPS_SCRIPT_URL", "")
SOLANA_RPC_URL = os.getenv("SOLANA_RPC_URL", "")
SOLANA_EXPLORER_BASE = os.getenv("SOLANA_EXPLORER_BASE", "https://solscan.io/tx")

if not BOT_TOKEN or not GEMINI_API_KEY:
    logger.critical("❌ ОШИБКА: Укажите BOT_TOKEN и GEMINI_API_KEY в .env")
    sys.exit(1)

DEFAULT_LANG = "ru"
ROLE_GUEST = "GUEST"
ROLE_VOLUNTEER = "VOLUNTEER"
ROLE_COORDINATOR = "COORDINATOR"
ROLE_WAREHOUSE_ADMIN = "WAREHOUSE_ADMIN"

MISSION_IDLE = "IDLE"
MISSION_PROPOSED = "PROPOSED"
MISSION_CLAIMED = "CLAIMED"
MISSION_PICKED_UP = "PICKED_UP"
MISSION_DELIVERY = "DELIVERY"
MISSION_VERIFIED = "VERIFIED"

MISSION_ACTIVE_STATES = {MISSION_CLAIMED, MISSION_PICKED_UP, MISSION_DELIVERY}

# ═══════════════════════════════════════════════════════════════════════════
# GOOGLE SHEETS
# ═══════════════════════════════════════════════════════════════════════════

GOOGLE_CREDENTIALS_PATH = os.getenv("GOOGLE_CREDENTIALS_PATH", "qaiyrym-credentials.json")
GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID", "")
GOOGLE_SHEET_NAME = os.getenv("GOOGLE_SHEET_NAME", "Волонтёры")
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

def get_sheets_client():
    """Инициализация клиента Google Sheets."""
    if not GOOGLE_SHEET_ID:
        logger.warning("[SHEETS] GOOGLE_SHEET_ID не установлен в .env")
        return None, None
    
    if not os.path.exists(GOOGLE_CREDENTIALS_PATH):
        logger.warning(f"[SHEETS] Файл {GOOGLE_CREDENTIALS_PATH} не найден")
        return None, None
    
    try:
        creds = Credentials.from_service_account_file(GOOGLE_CREDENTIALS_PATH, scopes=SCOPES)
        gc = gspread.authorize(creds)
        sheet = gc.open_by_key(GOOGLE_SHEET_ID)
        logger.info(f"[SHEETS] Подключено к Google Sheets: {GOOGLE_SHEET_NAME}")
@@ -75,108 +94,636 @@ def get_sheets_client():
        return None, None

def append_volunteer_to_sheets(user_id: str, name: str, age: int, skill: str, lang: str, username: str = "") -> bool:
    """Добавляет волонтёра в Google Sheets."""
    sheet, sheet_name = get_sheets_client()
    if not sheet:
        return False
    
    try:
        worksheet = sheet.worksheet(sheet_name)
        row = [user_id, name, age, skill, lang, username, datetime.now().isoformat()]
        worksheet.append_row(row, value_input_option="RAW")
        logger.info(f"[SHEETS] Волонтёр {name} добавлен")
        return True
    except Exception as e:
        logger.error(f"[SHEETS ERROR] {e}")
        return False

# ═══════════════════════════════════════════════════════════════════════════
# БАЗА ДАННЫХ
# ═══════════════════════════════════════════════════════════════════════════

USER_DB_FILE = "users_db.json"
USERS_DATA: Dict[str, Dict[str, Any]] = {}



def apps_script_post(payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """POST в Google Apps Script Web App API."""
    if not APPS_SCRIPT_URL:
        return None
    try:
        response = requests.post(APPS_SCRIPT_URL, json=payload, timeout=20, allow_redirects=True)
        response.raise_for_status()
        try:
            return response.json()
        except Exception:
            return {"raw": response.text}
    except Exception as e:
        logger.error("[APPS SCRIPT POST] %s", e)
        return None


def apps_script_get(params: Optional[Dict[str, Any]] = None) -> Optional[Any]:
    """GET из Google Apps Script Web App API."""
    if not APPS_SCRIPT_URL:
        return None
    try:
        response = requests.get(APPS_SCRIPT_URL, params=params or {}, timeout=20, allow_redirects=True)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        logger.error("[APPS SCRIPT GET] %s", e)
        return None

def load_users_db():
    """Загружает БД пользователей."""
    global USERS_DATA
    try:
        if os.path.exists(USER_DB_FILE):
            with open(USER_DB_FILE, "r", encoding="utf-8") as f:
                USERS_DATA = json.load(f)
                logger.info(f"[DB] Загружено {len(USERS_DATA)} пользователей")
        else:
            USERS_DATA = {}
    except Exception as e:
        logger.error(f"[DB ERROR] {e}")
        USERS_DATA = {}

def save_users_db():
    """Сохраняет БД пользователей."""
    try:
        with open(USER_DB_FILE, "w", encoding="utf-8") as f:
            json.dump(USERS_DATA, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"[DB ERROR] {e}")

def get_user_role(user_id: str) -> str:
    """Возвращает роль пользователя."""
    if user_id in USERS_DATA:
        return USERS_DATA[user_id].get("role", "GUEST")
    return "GUEST"
        return USERS_DATA[user_id].get("role", ROLE_GUEST)
    return ROLE_GUEST

def save_user_registration(user_id: str, name: str, age: int, skill: str, lang: str, username: str = "") -> bool:
    """Сохраняет регистрацию пользователя."""
    try:
        USERS_DATA[user_id] = {
            "user_id": user_id,
            "name": name,
            "age": age,
            "skill": skill,
            "lang": lang,
            "role": "MEMBER",
            "role": ROLE_VOLUNTEER,
            "registered_at": datetime.now().isoformat(),
        }
        save_users_db()
        logger.info(f"[DB] Пользователь {user_id} зарегистрирован: {name}")
        append_volunteer_to_sheets(user_id, name, age, skill, lang, username)
        return True
    except Exception as e:
        logger.error(f"[DB ERROR] {e}")
        return False

def set_user_language(user_id: str, lang: str):
    """Сохраняет язык пользователя."""
    if user_id not in USERS_DATA:
        USERS_DATA[user_id] = {"role": "GUEST"}
        USERS_DATA[user_id] = {"role": ROLE_GUEST}
    USERS_DATA[user_id]["lang"] = lang
    save_users_db()

def get_all_member_ids() -> List[str]:
    """Возвращает список волонтеров."""
    return [user_id for user_id, data in USERS_DATA.items() if data.get("role") == "MEMBER"]
    return [
        user_id
        for user_id, data in USERS_DATA.items()
        if data.get("role") in {ROLE_VOLUNTEER, ROLE_COORDINATOR}
    ]


def increment_user_sbt_rating(user_id: str, delta: int = 20) -> int:
    """Начисляет SBT-баллы пользователю и возвращает новый рейтинг."""
    if user_id not in USERS_DATA:
        USERS_DATA[user_id] = {"role": ROLE_GUEST}

    current = int(USERS_DATA[user_id].get("sbt_rating", 0) or 0)
    new_value = current + delta
    USERS_DATA[user_id]["sbt_rating"] = new_value
    USERS_DATA[user_id]["updated_at"] = datetime.now().isoformat()
    save_users_db()
    return new_value




def haversine_meters(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Расстояние между двумя точками в метрах."""
    r = 6371000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


async def record_sbt_on_solana(user_id: str, request_id: str, points: int = 20, retries: int = 3) -> Optional[str]:
    """Подготовка к интеграции Solana: retry-обертка + ссылка в explorer."""
    if not SOLANA_RPC_URL:
        logger.info("[SOLANA] RPC URL не настроен, пропускаем on-chain запись")
        return None

    for attempt in range(1, retries + 1):
        try:
            await asyncio.sleep(0.2)
            tx_sig = f"demo-{request_id}-{user_id}-{points}-{attempt}"
            return f"{SOLANA_EXPLORER_BASE}/{tx_sig}"
        except Exception as e:
            logger.warning("[SOLANA] attempt %s/%s failed: %s", attempt, retries, e)

    return None

class MissionOrchestrator:
    """Оркестратор миссий: статусы, права, таймер SLA и связь со складом."""

    def __init__(self):
        self.delivery_watchers: Dict[str, asyncio.Task] = {}
        self.claim_watchers: Dict[str, asyncio.Task] = {}

    @staticmethod
    def _worksheet(sheet, title: str):
        try:
            return sheet.worksheet(title)
        except Exception:
            return None

    def create_request(self, address: str, description: str, district: str = "", status: str = MISSION_IDLE) -> Optional[str]:
        """Создает новую заявку в Google Sheets и возвращает ее ID."""
        if APPS_SCRIPT_URL:
            payload = {
                "method": "CREATE",
                "address": address,
                "desc": description,
                "district": district,
                "status": status,
                "lat": 0,
                "lng": 0,
            }
            result = apps_script_post(payload) or {}
            return str(result.get("id") or result.get("request_id") or result.get("raw") or "") or None

        sheet, _ = get_sheets_client()
        if not sheet:
            return None
        ws = self._worksheet(sheet, "Requests")
        if not ws:
            return None

        headers = ws.row_values(1)
        required = ["ID", "Items_List", "District", "Status", "Assigned_Team_ID", "Warehouse_Confirmed_Time"]
        if not headers:
            ws.append_row(required, value_input_option="RAW")
            headers = required

        records = ws.get_all_records()
        max_id = 0
        for row in records:
            try:
                max_id = max(max_id, int(str(row.get("ID", "0") or 0)))
            except ValueError:
                continue
        new_id = str(max_id + 1)

        row_map = {
            "ID": new_id,
            "Items_List": description,
            "District": district,
            "Status": status,
            "Assigned_Team_ID": "",
            "Warehouse_Confirmed_Time": "",
            "Address": address,
            "Created_At": datetime.now().isoformat(),
        }
        row = [row_map.get(h, "") for h in headers]
        ws.append_row(row, value_input_option="RAW")
        return new_id

    def get_request_row(self, request_id: str) -> Optional[Dict[str, Any]]:
        if APPS_SCRIPT_URL:
            rows = apps_script_get({"method": "LIST"}) or []
            if isinstance(rows, list):
                for row in rows:
                    if str(row.get("id", row.get("ID", ""))) == str(request_id):
                        return row
            return None

        sheet, _ = get_sheets_client()
        if not sheet:
            return None
        ws = self._worksheet(sheet, "Requests")
        if not ws:
            return None
        for row in ws.get_all_records():
            if str(row.get("ID", "")) == str(request_id):
                return row
        return None

    def list_requests(self, user_id: str) -> List[Dict[str, Any]]:
        role = get_user_role(user_id)

        if APPS_SCRIPT_URL:
            rows = apps_script_get({"method": "LIST"}) or []
            result: List[Dict[str, Any]] = []
            if not isinstance(rows, list):
                return result
            for row in rows:
                status = row.get("status", row.get("Status", MISSION_IDLE))
                can_claim = role == ROLE_COORDINATOR and status in {MISSION_IDLE, MISSION_PROPOSED}
                result.append(
                    {
                        "id": str(row.get("id", row.get("ID", ""))),
                        "items_list": row.get("items_list", row.get("desc", row.get("Items_List", ""))),
                        "district": row.get("district", row.get("District", "")),
                        "address": row.get("address", row.get("Address", "")),
                        "status": status,
                        "assigned_team_id": row.get("assigned_team_id", row.get("Assigned_Team_ID", "")),
                        "warehouse_confirmed_time": row.get("warehouse_confirmed_time", row.get("Warehouse_Confirmed_Time", "")),
                        "lat": row.get("lat", row.get("Lat", 0)),
                        "lng": row.get("lng", row.get("Lng", 0)),
                        "can_claim": can_claim,
                    }
                )
            return result

        sheet, _ = get_sheets_client()
        if not sheet:
            return []

        ws = self._worksheet(sheet, "Requests")
        if not ws:
            logger.warning("[MISSION] Лист Requests не найден")
            return []

        rows = ws.get_all_records()
        result: List[Dict[str, Any]] = []
        for row in rows:
            status = row.get("Status", MISSION_IDLE)
            can_claim = role == ROLE_COORDINATOR and status in {MISSION_IDLE, MISSION_PROPOSED}
            result.append(
                {
                    "id": str(row.get("ID", "")),
                    "items_list": row.get("Items_List", ""),
                    "district": row.get("District", ""),
                    "address": row.get("Address", ""),
                    "status": status,
                    "assigned_team_id": row.get("Assigned_Team_ID", ""),
                    "warehouse_confirmed_time": row.get("Warehouse_Confirmed_Time", ""),
                    "lat": row.get("Lat", 0),
                    "lng": row.get("Lng", 0),
                    "can_claim": can_claim,
                }
            )
        return result

    def propose_request(self, request_id: str, volunteer_id: str) -> bool:
        sheet, _ = get_sheets_client()
        if not sheet:
            return False
        ws = self._worksheet(sheet, "Requests")
        if not ws:
            return False

        cell = ws.find(str(request_id), in_column=1)
        if not cell:
            return False

        status_col = ws.find("Status").col
        ws.update_cell(cell.row, status_col, MISSION_PROPOSED)
        logger.info("[MISSION] Предложение по заявке %s от %s", request_id, volunteer_id)
        return True

    def claim_request(self, request_id: str, coordinator_id: str, team_id: str) -> bool:
        if get_user_role(coordinator_id) != ROLE_COORDINATOR:
            return False
        sheet, _ = get_sheets_client()
        if not sheet:
            return False
        ws = self._worksheet(sheet, "Requests")
        if not ws:
            return False

        cell = ws.find(str(request_id), in_column=1)
        if not cell:
            return False

        status_col = ws.find("Status").col
        team_col = ws.find("Assigned_Team_ID").col
        ws.update_cell(cell.row, status_col, MISSION_CLAIMED)
        ws.update_cell(cell.row, team_col, team_id)
        logger.info("[MISSION] Заявка %s взята координатором %s", request_id, coordinator_id)
        return True

    def warehouse_issue(self, request_id: str) -> bool:
        """Подтверждение выдачи со склада -> PICKED_UP + timestamp."""
        sheet, _ = get_sheets_client()
        if not sheet:
            return False
        ws = self._worksheet(sheet, "Requests")
        if not ws:
            return False

        cell = ws.find(str(request_id), in_column=1)
        if not cell:
            return False

        status_col = ws.find("Status").col
        ts_col = ws.find("Warehouse_Confirmed_Time").col
        ws.update_cell(cell.row, status_col, MISSION_PICKED_UP)
        ws.update_cell(cell.row, ts_col, datetime.now().isoformat())
        logger.info("[MISSION] Склад выдал заявку %s", request_id)
        return True

    async def schedule_delivery_timeout(self, bot: Bot, request_id: str, coordinator_id: str) -> None:
        """Таймер 3 часа: если не VERIFIED, уведомить администратора и координатора."""
        if request_id in self.delivery_watchers and not self.delivery_watchers[request_id].done():
            self.delivery_watchers[request_id].cancel()

        async def _watcher():
            await asyncio.sleep(10800)
            current = self.get_request_status(request_id)
            if current != MISSION_VERIFIED:
                alert = f"⚠️ Внимание! Срок доставки заявки #{request_id} истек!"
                if ADMIN_ID:
                    await bot.send_message(chat_id=int(ADMIN_ID), text=alert)
                await bot.send_message(chat_id=int(coordinator_id), text=alert)

        self.delivery_watchers[request_id] = asyncio.create_task(_watcher())

    def get_request_status(self, request_id: str) -> Optional[str]:
        sheet, _ = get_sheets_client()
        if not sheet:
            return None
        ws = self._worksheet(sheet, "Requests")
        if not ws:
            return None
        cell = ws.find(str(request_id), in_column=1)
        if not cell:
            return None
        status_col = ws.find("Status").col
        return ws.cell(cell.row, status_col).value

    def mark_verified(self, request_id: str) -> bool:
        sheet, _ = get_sheets_client()
        if not sheet:
            return False
        ws = self._worksheet(sheet, "Requests")
        if not ws:
            return False
        cell = ws.find(str(request_id), in_column=1)
        if not cell:
            return False
        status_col = ws.find("Status").col
        ws.update_cell(cell.row, status_col, MISSION_VERIFIED)

        watcher = self.delivery_watchers.get(request_id)
        if watcher and not watcher.done():
            watcher.cancel()
        return True


    def update_verified_report(self, request_id: str, user_id: str, lat: float, lng: float, verdict: str = "APPROVED") -> bool:
        """Финальный шаг верификации: статус VERIFIED + данные отчета в Google Sheets."""
        if APPS_SCRIPT_URL:
            payload = {
                "method": "VERIFY",
                "request_id": str(request_id),
                "user_id": str(user_id),
                "status": MISSION_VERIFIED,
                "lat": lat,
                "lng": lng,
                "verdict": verdict,
                "verified_at": datetime.now().isoformat(),
            }
            result = apps_script_post(payload)
            if not result:
                return False
            increment_user_sbt_rating(str(user_id), 20)
            watcher = self.delivery_watchers.get(request_id)
            if watcher and not watcher.done():
                watcher.cancel()
            return True

        sheet, _ = get_sheets_client()
        if not sheet:
            return False

        ws = self._worksheet(sheet, "Requests")
        if not ws:
            return False

        cell = ws.find(str(request_id), in_column=1)
        if not cell:
            return False

        headers = ws.row_values(1)

        def col(name: str):
            if name in headers:
                return headers.index(name) + 1
            return None

        status_col = col("Status")
        verified_at_col = col("Verified_At")
        verified_by_col = col("Verified_By")
        lat_col = col("Delivered_Lat")
        lng_col = col("Delivered_Lng")
        verdict_col = col("AI_Verdict")

        if status_col:
            ws.update_cell(cell.row, status_col, MISSION_VERIFIED)
        if verified_at_col:
            ws.update_cell(cell.row, verified_at_col, datetime.now().isoformat())
        if verified_by_col:
            ws.update_cell(cell.row, verified_by_col, str(user_id))
        if lat_col:
            ws.update_cell(cell.row, lat_col, str(lat))
        if lng_col:
            ws.update_cell(cell.row, lng_col, str(lng))
        if verdict_col:
            ws.update_cell(cell.row, verdict_col, verdict)

        increment_user_sbt_rating(str(user_id), 20)

        watcher = self.delivery_watchers.get(request_id)
        if watcher and not watcher.done():
            watcher.cancel()
        return True

    def reset_request_to_idle(self, request_id: str) -> bool:
        sheet, _ = get_sheets_client()
        if not sheet:
            return False
        ws = self._worksheet(sheet, "Requests")
        if not ws:
            return False
        cell = ws.find(str(request_id), in_column=1)
        if not cell:
            return False

        status_col = ws.find("Status").col
        ws.update_cell(cell.row, status_col, MISSION_IDLE)
        team_col = ws.find("Assigned_Team_ID")
        if team_col:
            ws.update_cell(cell.row, team_col.col, "")
        logger.info("[MISSION] Заявка %s возвращена в IDLE", request_id)
        return True

    def get_request_location(self, request_id: str) -> Optional[tuple[float, float]]:
        sheet, _ = get_sheets_client()
        if not sheet:
            return None
        ws = self._worksheet(sheet, "Requests")
        if not ws:
            return None
        records = ws.get_all_records()
        for row in records:
            if str(row.get("ID", "")) == str(request_id):
                lat = row.get("Lat")
                lng = row.get("Lng")
                if lat is None or lng is None or lat == "" or lng == "":
                    return None
                try:
                    return float(lat), float(lng)
                except Exception:
                    return None
        return None

    def validate_delivery_location(self, request_id: str, lat: float, lng: float, max_distance_m: int = 300) -> tuple[bool, Optional[float]]:
        req_location = self.get_request_location(request_id)
        if not req_location:
            return False, None
        distance = haversine_meters(req_location[0], req_location[1], lat, lng)
        return distance <= max_distance_m, distance

    async def schedule_dead_mission_watch(self, bot: Bot, request_id: str, coordinator_id: str) -> None:
        """Через 4 часа пингует координатора; при тишине возвращает заявку в IDLE."""
        if request_id in self.claim_watchers and not self.claim_watchers[request_id].done():
            self.claim_watchers[request_id].cancel()

        async def _watcher():
            await asyncio.sleep(14400)
            status = self.get_request_status(request_id)
            if status in MISSION_ACTIVE_STATES:
                ping = f"⚠️ Эй, по заявке #{request_id} нет отчета 4 часа. Нужна помощь?"
                await bot.send_message(chat_id=int(coordinator_id), text=ping)
                if ADMIN_ID:
                    await bot.send_message(chat_id=int(ADMIN_ID), text=ping)

                await asyncio.sleep(1800)
                status_after = self.get_request_status(request_id)
                if status_after in MISSION_ACTIVE_STATES:
                    self.reset_request_to_idle(request_id)
                    msg = f"♻️ Заявка #{request_id} автоматически возвращена в IDLE из-за отсутствия отчета."
                    await bot.send_message(chat_id=int(coordinator_id), text=msg)
                    if ADMIN_ID:
                        await bot.send_message(chat_id=int(ADMIN_ID), text=msg)

        self.claim_watchers[request_id] = asyncio.create_task(_watcher())


MISSION_ORCHESTRATOR = MissionOrchestrator()

INTENT_TAG_RE = re.compile(r"\[(INTENT_CLAIM|INTENT_VERIFY):(\d+)\]")

def parse_intent_tag(reply: str) -> tuple[Optional[str], Optional[str], str]:
    """Парсит технический тег интента в начале ответа Gemini."""
    if not reply:
        return None, None, ""

    match = INTENT_TAG_RE.search(reply)
    if not match:
        return None, None, reply

    intent, request_id = match.group(1), match.group(2)
    clean = INTENT_TAG_RE.sub("", reply, count=1).strip()
    return intent, request_id, clean


def build_strict_verification_prompt(items_list: str, address: str, user_report: str) -> str:
    return (
        "Проверь фото-отчет миссии. "
        f"Задание: {items_list}. Адрес: {address}. "
        "Если на фото видно факт передачи помощи/пакет у двери и контекст похож на целевую локацию, "
        "начни ответ строго со слова APPROVED. Иначе верни отказ с причиной. "
        f"Контекст волонтера: {user_report}"
    )


def build_mission_guide_text(request_id: str) -> str:
    return (
        f"🚀 Миссия #{request_id} началась!\n"
        "1) Прибудьте по адресу семьи.\n"
        "2) На месте зафиксируйте геопозицию (lat/lng).\n"
        "3) Сделайте фото передачи/коробки у двери.\n"
        "4) Отправьте отчет в Mini App.\n"
        "Статусы: Фото получено → ИИ проверяет → on-chain запись SBT."
    )


def requests_keyboard(requests_list: List[Dict[str, Any]], role: str) -> InlineKeyboardMarkup:
    """Кнопки для быстрых действий без ручного ввода ID."""
    buttons = []
    for req in requests_list[:10]:
        req_id = req.get("id", "")
        district = req.get("district", "")
        status = req.get("status", MISSION_IDLE)

        if role == ROLE_COORDINATOR and req.get("can_claim"):
            text = f"✅ #{req_id} | {district}"
            cb = f"confirm_claim:{req_id}"
        elif role in {ROLE_VOLUNTEER, ROLE_COORDINATOR} and status in {MISSION_IDLE, MISSION_PROPOSED}:
            text = f"🤝 #{req_id} | {district}"
            cb = f"confirm_propose:{req_id}"
        else:
            continue

        buttons.append([InlineKeyboardButton(text=text[:64], callback_data=cb)])

    if not buttons:
        buttons = [[InlineKeyboardButton(text="Обновить список", callback_data="mission:refresh_requests")]]

    return InlineKeyboardMarkup(inline_keyboard=buttons)


# ═══════════════════════════════════════════════════════════════════════════
# KNOWLEDGE.txt
# ═══════════════════════════════════════════════════════════════════════════

def load_manifest() -> str:
    """Загружает knowledge.txt."""
    paths = [
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "knowledge.txt"),
        os.path.join(os.getcwd(), "knowledge.txt"),
    ]
    for path in paths:
        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read().strip()
            if content:
                logger.info(f"[MANIFEST] Загружен knowledge.txt ({len(content)} символов)")
                return content
        except FileNotFoundError:
            continue
        except Exception as e:
            logger.error(f"[MANIFEST] ОШИБКА: {e}")
            continue
    logger.warning("[MANIFEST] knowledge.txt не найден")
    return ""
@@ -214,54 +761,67 @@ def get_chat_system_instruction(user_lang: str, role: str = "GUEST", chat_histor
        "СТРАТЕГИЯ:\n"
        "1. ИНТЕРВЬЮ: Каждый ответ = вопрос в конце\n"
        "2. ПОРЦИИ: Не рассказывай всё сразу, давай 30% информации\n"
        "3. ГИБКОСТЬ: 3-4 предложения обычно, подробнее если просит\n"
        "4. ЛИЧНОСТЬ: Используй 'Кстати, а ты...', 'Интересно узнать...'\n"
        "5. ЭКСТРАВЕРТ: Предлагай помощь, интересуйся деталями\n\n"
        
        "ТЕХНИКА:\n"
        f"• Язык: {lang_name} ({lang})\n"
        "• Используй <code> для терминов\n"
        "• Оформляй важное <b>жирным</b>\n"
        "• Избегай скучных списков\n"
    )
    
    # Приветствие только при старте
    if chat_history_len <= 2:
        base += (
            "\n⭐ ПЕРВОЕ СООБЩЕНИЕ:\n"
            "Ты МОЖЕШЬ поздороваться и задать первый вопрос:\n"
            "'Привет! Я — Компас, координатор QAIYRYM. "
            "Как дела? Расскажи, что тебя привело в наш проект?'\n"
        )
    else:
        base += "\n⭐ ПОСЛЕДУЮЩИЕ: НЕ повторяй приветствие, продолжи диалог.\n"
    
    if role == "MEMBER":
    if role in {ROLE_VOLUNTEER, ROLE_COORDINATOR, ROLE_WAREHOUSE_ADMIN}:
        base += "\n👤 РЕЖИМ УЧАСТНИКА: Обсуждай глубокие темы, детали помощи."
        base += (
            "\n🚨 Если пользователь пишет из активной доставки (например: дверь не открывают), "
            "действуй как экстренный оператор: дай пошаговый протокол, тайминг ожидания "
            "и что фиксировать в отчёте."
        )
    else:
        base += "\n👤 РЕЖИМ ГОСТЯ: Будь дружелюбен, поощряй присоединиться."

    base += (
        "\n\n🛠 ТЕХНИЧЕСКИЙ РЕЖИМ (для интеграции с бэкендом):"
        "\nЕсли понимаешь намерение пользователя выполнить действие по миссии, добавляй тег в НАЧАЛЕ ответа:"
        "\n- [INTENT_CLAIM:ID] — пользователь хочет взять заявку"
        "\n- [INTENT_VERIFY:ID] — пользователь хочет подтвердить доставку"
        "\nПосле тега пиши обычный человеческий ответ с уточнением/подтверждением."
    )
    
    return base

async def ask_gemini(prompt: str, system_prompt: str | None = None, user_lang: str = DEFAULT_LANG, skip_lang_instruction: bool = False) -> str:
    """Вызов Gemini с таймаутом и обработкой ошибок."""
    base = system_prompt or ""
    if not skip_lang_instruction:
        lang = user_lang if user_lang in ("ru", "kz") else DEFAULT_LANG
        lang_name = "русском" if lang == "ru" else "казахском"
        lang_instruction = f"Отвечай на {lang_name} ({lang})."
        system_instruction = f"{base}\n\n{lang_instruction}" if base else lang_instruction
    else:
        system_instruction = base

    def _generate_sync(model_name: str) -> str:
        """Синхронный вызов Gemini API."""
        try:
            client = get_gemini_client()
            config = types.GenerateContentConfig(
                max_output_tokens=512,
                temperature=0.7,
                system_instruction=system_instruction if system_instruction else None
            )
            response = client.models.generate_content(model=model_name, contents=prompt, config=config)
            return response.text.strip() if response.text else "Извините, не могу ответить."
@@ -391,100 +951,100 @@ def about_submenu_keyboard(lang: str = DEFAULT_LANG) -> InlineKeyboardMarkup:
})

# ═══════════════════════════════════════════════════════════════════════════
# HANDLERS
# ═══════════════════════════════════════════════════════════════════════════

router = Router()

@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    user_id = str(message.from_user.id)
    logger.info(f"[START] User {user_id}")
    await state.clear()
    await state.set_state(OnboardingState.choose_language)
    await message.answer(t("choose_lang", DEFAULT_LANG), reply_markup=lang_keyboard())

@router.callback_query(F.data.startswith("lang:"))
async def process_lang(callback: CallbackQuery, state: FSMContext) -> None:
    lang = callback.data.split(":")[1]
    user_id = str(callback.from_user.id)
    set_user_language(user_id, lang)
    await state.update_data(lang=lang)
    role = get_user_role(user_id)
    logger.info(f"[LANG] User {user_id} выбрал {lang}, роль: {role}")
    
    if role == "MEMBER":
    if role in {ROLE_VOLUNTEER, ROLE_COORDINATOR, ROLE_WAREHOUSE_ADMIN}:
        await state.set_state(OnboardingState.member_menu)
        await callback.message.edit_text(t("intro_member", lang), reply_markup=member_menu_keyboard(lang))
    else:
        await state.set_state(OnboardingState.guest_menu)
        await callback.message.edit_text(t("intro_guest", lang), reply_markup=guest_menu_keyboard(lang))
    await callback.answer()

@router.callback_query(F.data == "menu:chat")
async def menu_chat(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    lang = data.get("lang") or DEFAULT_LANG
    logger.info(f"[MENU] User {callback.from_user.id} -> Общение")
    await state.set_state(OnboardingState.chat_mode)
    await callback.message.answer(t("chat_mode_on", lang))
    await callback.answer()

@router.callback_query(F.data == "menu:about")
async def menu_about(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    lang = data.get("lang") or DEFAULT_LANG
    logger.info(f"[MENU] User {callback.from_user.id} -> О проекте")
    await state.set_state(OnboardingState.about_submenu)
    await callback.message.edit_text(t("about", lang), reply_markup=about_submenu_keyboard(lang))
    await callback.answer()

@router.callback_query(F.data.startswith("about:"))
async def about_submenu_handler(callback: CallbackQuery, state: FSMContext) -> None:
    action = callback.data.split(":")[1]
    data = await state.get_data()
    lang = data.get("lang") or DEFAULT_LANG
    
    text_map = {
        "mission": t("mission", lang),
        "creator": t("creator", lang),
        "partners": t("partners", lang),
        "details": t("details", lang),
    }
    text = text_map.get(action, t("about", lang))
    await callback.message.edit_text(text, reply_markup=about_submenu_keyboard(lang))
    await callback.answer()

@router.callback_query(F.data == "menu:back_to_main")
async def back_to_main_menu(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    lang = data.get("lang") or DEFAULT_LANG
    user_id = str(callback.from_user.id)
    role = get_user_role(user_id)
    
    if role == "MEMBER":
    if role in {ROLE_VOLUNTEER, ROLE_COORDINATOR, ROLE_WAREHOUSE_ADMIN}:
        await state.set_state(OnboardingState.member_menu)
        await callback.message.edit_text(t("intro_member", lang), reply_markup=member_menu_keyboard(lang))
    else:
        await state.set_state(OnboardingState.guest_menu)
        await callback.message.edit_text(t("intro_guest", lang), reply_markup=guest_menu_keyboard(lang))
    await callback.answer()

@router.callback_query(F.data == "menu:join")
async def menu_join(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    lang = data.get("lang") or DEFAULT_LANG
    logger.info(f"[MENU] User {callback.from_user.id} -> Регистрация")
    await state.set_state(OnboardingState.registration_name)
    await callback.message.answer(t("join_intro", lang) + "\n\n" + t("ask_name", lang))
    await callback.answer()

@router.message(OnboardingState.registration_name, F.text)
async def reg_name(message: Message, state: FSMContext) -> None:
    name = message.text.strip()
    await state.update_data(name=name)
    data = await state.get_data()
    lang = data.get("lang") or DEFAULT_LANG
    await state.set_state(OnboardingState.registration_age)
    await message.answer(t("ask_age", lang))

@@ -532,129 +1092,389 @@ async def reg_skill(message: Message, state: FSMContext) -> None:

@router.callback_query(F.data == "menu:instruction")
async def menu_instruction(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    lang = data.get("lang") or DEFAULT_LANG
    logger.info(f"[MENU] User {callback.from_user.id} -> Инструкция")
    await callback.message.answer(t("instruction", lang), reply_markup=member_menu_keyboard(lang))
    await callback.answer()

@router.callback_query(F.data == "menu:profile")
async def menu_profile(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    lang = data.get("lang") or DEFAULT_LANG

    if not WEBAPP_URL:
        await callback.message.answer("❌ Мини-приложение пока не настроено.")
        await callback.answer()
        return

    keyboard = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="Открыть Mini App", web_app=WebAppInfo(url=WEBAPP_URL))
    ]])
    await callback.message.answer("🧭 Откройте мини-приложение", reply_markup=keyboard)
    await callback.answer()

@router.callback_query(F.data == "mission:refresh_requests")
async def mission_refresh_requests(callback: CallbackQuery) -> None:
    user_id = str(callback.from_user.id)
    role = get_user_role(user_id)
    requests = MISSION_ORCHESTRATOR.list_requests(user_id)
    if not requests:
        await callback.message.answer("Список заявок пуст или Google Sheets недоступен.")
        await callback.answer()
        return

    await callback.message.answer(
        "📌 Обновленный список заявок:",
        reply_markup=requests_keyboard(requests, role)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("confirm_propose:"))
async def mission_confirm_propose(callback: CallbackQuery) -> None:
    request_id = callback.data.split(":", 1)[1]
    user_id = str(callback.from_user.id)
    role = get_user_role(user_id)

    if role not in {ROLE_VOLUNTEER, ROLE_COORDINATOR}:
        await callback.answer("Нет доступа", show_alert=True)
        return

    ok = MISSION_ORCHESTRATOR.propose_request(request_id, user_id)
    text = "✅ Предложение отправлено координатору." if ok else "❌ Не удалось отправить предложение."
    await callback.message.answer(text)
    await callback.answer()


@router.callback_query(F.data.startswith("confirm_claim:"))
async def mission_confirm_claim(callback: CallbackQuery) -> None:
    request_id = callback.data.split(":", 1)[1]
    user_id = str(callback.from_user.id)

    if get_user_role(user_id) != ROLE_COORDINATOR:
        await callback.answer("Взять заявку может только COORDINATOR", show_alert=True)
        return

    ok = MISSION_ORCHESTRATOR.claim_request(request_id, user_id, team_id=user_id)
    text = "✅ Заявка закреплена за вашей командой." if ok else "❌ Не удалось взять заявку."
    await callback.message.answer(text)
    if ok:
        await MISSION_ORCHESTRATOR.schedule_dead_mission_watch(callback.bot, request_id, user_id)
        await callback.message.answer(build_mission_guide_text(request_id))
    await callback.answer()


@router.callback_query(F.data.startswith("confirm_verify:"))
async def mission_confirm_verify(callback: CallbackQuery) -> None:
    request_id = callback.data.split(":", 1)[1]
    user_id = str(callback.from_user.id)
    role = get_user_role(user_id)

    if role not in {ROLE_COORDINATOR, ROLE_WAREHOUSE_ADMIN}:
        await callback.answer("Подтверждение доступно координатору/складу", show_alert=True)
        return

    ok = MISSION_ORCHESTRATOR.mark_verified(request_id)
    text = "✅ Доставка подтверждена: VERIFIED." if ok else "❌ Не удалось подтвердить заявку."
    await callback.message.answer(text)
    await callback.answer()


@router.message(OnboardingState.chat_mode, F.text)
async def chat_mode_message(message: Message, state: FSMContext) -> None:
    """Обработчик чата с историей и фильтрацией."""
    user_text = (message.text or "").strip()
    if not user_text:
        return
    
    # ФИЛЬТР: пропускаем пустые слова
    skip_words = ["ок", "да", "нет", "привет", "привет!", "ха", "оке", "хорошо", "спасибо", "пока"]
    if user_text.lower() in skip_words:
        logger.info(f"[CHAT] Пустое сообщение скипнуто: {user_text}")
        return
    
    user_id = str(message.from_user.id)
    data = await state.get_data()
    lang = data.get("lang") or DEFAULT_LANG
    role = get_user_role(user_id)
    
    # ИНИЦИАЛИЗИРУЕМ или берем историю
    if "chat_history" not in data:
        data["chat_history"] = []
    
    chat_history = data["chat_history"]
    logger.info(f"[CHAT] User {user_id} ({role}) -> {user_text[:50]}... (история: {len(chat_history)} сообщений)")
    
    # ДОБАВЛЯЕМ сообщение в историю
    chat_history.append({"role": "user", "content": user_text})
    
    # Эффект печатания
    await message.bot.send_chat_action(chat_id=message.chat.id, action="typing")
    
    # ФОРМИРУЕМ системный промпт с длиной истории
    system_instruction = get_chat_system_instruction(lang, role=role, chat_history_len=len(chat_history))
    
    # ДОБАВЛЯЕМ контекст в конец
    if KNOWLEDGE_MANIFEST:
        system_instruction += f"\n\n[CONTEXT_DATA]\n{KNOWLEDGE_MANIFEST}\n[END_CONTEXT_DATA]"
    
    # ФОРМАТИРУЕМ историю для Gemini
    formatted_messages = []
    for msg in chat_history:
        prefix = "🧑 ПОЛЬЗОВАТЕЛЬ:" if msg["role"] == "user" else "🤖 КОМПАС:"
        formatted_messages.append(f"{prefix} {msg['content']}")
    
    full_prompt = "\n\n".join(formatted_messages)
    
    try:
        # ВЫЗЫВАЕМ Gemini
        reply = await ask_gemini(full_prompt, system_instruction, user_lang=lang, skip_lang_instruction=True)
        

        intent, request_id, clean_reply = parse_intent_tag(reply)

        # СОХРАНЯЕМ ответ в историю
        chat_history.append({"role": "model", "content": reply})
        
        chat_history.append({"role": "model", "content": clean_reply or reply})

        # ОГРАНИЧИВАЕМ память (max 20 сообщений)
        if len(chat_history) > 20:
            chat_history = chat_history[-20:]
        

        await state.update_data(chat_history=chat_history)
        
        # ОТПРАВЛЯЕМ ответ - используем html.quote для безопасности
        safe_reply = html.quote(reply)

        if intent == "INTENT_CLAIM" and request_id:
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✅ Подтверждаю", callback_data=f"confirm_claim:{request_id}")],
                [InlineKeyboardButton(text="❌ Отмена", callback_data="menu:chat")],
            ])
            safe_reply = html.quote(clean_reply or f"Подтверждаете, что берете заявку #{request_id}?")
            await message.answer(safe_reply, parse_mode=ParseMode.HTML, reply_markup=keyboard)
            return

        if intent == "INTENT_VERIFY" and request_id:
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✅ Завершить миссию", callback_data=f"confirm_verify:{request_id}")],
                [InlineKeyboardButton(text="❌ Отмена", callback_data="menu:chat")],
            ])
            safe_reply = html.quote(clean_reply or f"Подтверждаете завершение заявки #{request_id}?")
            await message.answer(safe_reply, parse_mode=ParseMode.HTML, reply_markup=keyboard)
            return

        # ОТПРАВЛЯЕМ обычный ответ
        safe_reply = html.quote(clean_reply or reply)
        await message.answer(safe_reply, parse_mode=ParseMode.HTML)
        
    except Exception as e:
        logger.error(f"[CHAT ERROR] {e}")
        await message.answer("Я немного завис, попробуй еще раз!")

@router.message(OnboardingState.guest_menu, F.text)
async def guest_menu_text(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    lang = data.get("lang") or DEFAULT_LANG
    await message.answer(t("use_menu_buttons", lang), reply_markup=guest_menu_keyboard(lang))

@router.message(OnboardingState.member_menu, F.text)
async def member_menu_text(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    lang = data.get("lang") or DEFAULT_LANG
    await message.answer(t("use_menu_buttons", lang), reply_markup=member_menu_keyboard(lang))



@router.message(Command("requests"))
async def cmd_requests(message: Message) -> None:
    """Список заявок с флагом can_claim и кнопками быстрого действия."""
    user_id = str(message.from_user.id)
    requests = MISSION_ORCHESTRATOR.list_requests(user_id)
    role = get_user_role(user_id)

    if not requests:
        await message.answer("Список заявок пуст или Google Sheets недоступен.")
        return

    lines = [f"📋 Роль: <b>{role}</b>"]
    for req in requests[:20]:
        action = "Взять заявку" if req["can_claim"] else "Предложить команде"
        lines.append(
            f"• #{req['id']} | {req['district']} | <code>{req['status']}</code> | "
            f"can_claim=<b>{str(req['can_claim']).lower()}</b> | {action}"
        )

    await message.answer("\n".join(lines), reply_markup=requests_keyboard(requests, role))


@router.message(Command("propose"))
async def cmd_propose(message: Message) -> None:
    """Волонтер предлагает заявку команде: /propose <request_id>"""
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Использование: /propose <request_id>")
        return

    user_id = str(message.from_user.id)
    role = get_user_role(user_id)
    if role not in {ROLE_VOLUNTEER, ROLE_COORDINATOR}:
        await message.answer("❌ Только волонтёры/координаторы могут предлагать заявки.")
        return

    request_id = parts[1].strip()
    ok = MISSION_ORCHESTRATOR.propose_request(request_id, user_id)
    await message.answer("✅ Предложение отправлено координатору (Red Dot)." if ok else "❌ Не удалось обновить заявку.")


@router.message(Command("claim"))
async def cmd_claim(message: Message) -> None:
    """Координатор берет заявку: /claim <request_id> <team_id>"""
    parts = message.text.split(maxsplit=2)
    if len(parts) < 3:
        await message.answer("Использование: /claim <request_id> <team_id>")
        return

    user_id = str(message.from_user.id)
    if get_user_role(user_id) != ROLE_COORDINATOR:
        await message.answer("❌ Кнопка 'Взять заявку' доступна только координатору.")
        return

    request_id, team_id = parts[1].strip(), parts[2].strip()
    ok = MISSION_ORCHESTRATOR.claim_request(request_id, user_id, team_id)
    await message.answer("✅ Заявка зафиксирована за вашей командой." if ok else "❌ Не удалось взять заявку.")
    if ok:
        await MISSION_ORCHESTRATOR.schedule_dead_mission_watch(message.bot, request_id, user_id)
        await message.answer(build_mission_guide_text(request_id))


@router.message(Command("warehouse_issue"))
async def cmd_warehouse_issue(message: Message, bot: Bot) -> None:
    """Интерфейс кладовщика: /warehouse_issue <request_id> <coordinator_id>"""
    parts = message.text.split(maxsplit=2)
    if len(parts) < 3:
        await message.answer("Использование: /warehouse_issue <request_id> <coordinator_id>")
        return

    user_id = str(message.from_user.id)
    if get_user_role(user_id) != ROLE_WAREHOUSE_ADMIN:
        await message.answer("❌ Команда доступна только роли WAREHOUSE_ADMIN.")
        return

    request_id, coordinator_id = parts[1].strip(), parts[2].strip()
    ok = MISSION_ORCHESTRATOR.warehouse_issue(request_id)
    if not ok:
        await message.answer("❌ Не удалось подтвердить выдачу на складе.")
        return

    await MISSION_ORCHESTRATOR.schedule_delivery_timeout(bot, request_id, coordinator_id)
    await message.answer("✅ Выдача подтверждена. Команда переведена в режим 'Доставка'.")
    await bot.send_message(chat_id=int(coordinator_id), text=f"📦 Заявка #{request_id}: склад подтвердил выдачу. Переход в DELIVERY.")


@router.message(Command("verify"))
async def cmd_verify(message: Message) -> None:
    """Закрытие миссии: /verify <request_id> <lat> <lng> <report_text>."""
    parts = (message.text or "").split(maxsplit=4)
    if len(parts) < 5:
        await message.answer("Использование: /verify <request_id> <lat> <lng> <отчет>")
        return

    request_id = parts[1].strip()

    try:
        lat, lng = float(parts[2]), float(parts[3])
    except ValueError:
        await message.answer("❌ lat/lng должны быть числами.")
        return

    user_report = parts[4].strip()

    is_ok, distance = MISSION_ORCHESTRATOR.validate_delivery_location(request_id, lat, lng, max_distance_m=300)
    if not is_ok:
        if distance is None:
            await message.answer("❌ Нет координат заявки в Sheets (Lat/Lng). Верификация отклонена.")
        else:
            await message.answer(f"❌ Геопозиция не совпадает: {distance:.0f}м (>300м). Верификация отклонена.")
        return

    request_row = MISSION_ORCHESTRATOR.get_request_row(request_id) or {}
    items_list = str(request_row.get("Items_List", "Помощь семье"))
    address = str(request_row.get("Address", request_row.get("District", "локация не указана")))

    await message.answer("📥 Фото получено. ИИ проверяет...")
    strict_prompt = build_strict_verification_prompt(items_list, address, user_report)
    verdict = await ask_gemini(strict_prompt, user_lang=DEFAULT_LANG, skip_lang_instruction=False)
    is_approved = verdict.strip().upper().startswith("APPROVED")

    if not is_approved:
        await message.answer(f"❌ ИИ не подтвердил отчет: {html.quote(verdict)}")
        return

    ok = MISSION_ORCHESTRATOR.update_verified_report(
        request_id=request_id,
        user_id=str(message.from_user.id),
        lat=lat,
        lng=lng,
        verdict=verdict,
    )
    if not ok:
        await message.answer("❌ Не удалось записать VERIFIED в Google Sheets.")
        return

    user_id = str(message.from_user.id)
    new_rating = int(USERS_DATA.get(user_id, {}).get("sbt_rating", 0))

    await message.answer("✅ ИИ одобрил. Данные внесены в реестр Google Sheets.")
    await message.answer(f"🏆 Верификация пройдена! +20 SBT баллов. Твой рейтинг: {new_rating}")
    await message.answer("✅ ИИ одобрил. Записываю SBT в блокчейн...")
    tx_url = await record_sbt_on_solana(user_id, request_id)
    if tx_url:
        await message.answer(f"🎉 Успех! VERIFIED + on-chain запись.\n🔗 {tx_url}")
    else:
        await message.answer("✅ VERIFIED сохранен. On-chain запись в очереди (RPC не настроен).")

@router.message(F.text.startswith("админ создать"))
async def admin_create_task(message: Message) -> None:
    """Админ создает заявку: админ создать [Адрес] [Описание]."""
    user_id = str(message.from_user.id)
    if not ADMIN_ID or user_id != ADMIN_ID:
        await message.answer("❌ Нет доступа.")
        return

    parts = (message.text or "").split(maxsplit=3)
    if len(parts) < 4:
        await message.answer("⚠️ Формат: админ создать [Адрес] [Описание]")
        return

    address = parts[2].strip()
    description = parts[3].strip()

    new_id = MISSION_ORCHESTRATOR.create_request(address=address, description=description, district=address, status=MISSION_IDLE)
    if not new_id:
        await message.answer("❌ Не удалось создать заявку в Google Sheets.")
        return

    await message.answer(f"✅ Задание #{new_id} создано и появилось в Mini App!")

@router.message(Command("broadcast"))
async def cmd_broadcast(message: Message, state: FSMContext, bot: Bot) -> None:
    user_id = str(message.from_user.id)
    if not ADMIN_ID or user_id != ADMIN_ID:
        await message.answer("❌ Нет доступа.")
        return
    
    broadcast_text = message.text.replace("/broadcast", "").strip()
    if not broadcast_text:
        await message.answer("❌ Укажите текст: /broadcast <текст>")
        return
    
    logger.info(f"[BROADCAST] Администратор {user_id} отправляет рассылку")
    member_ids = get_all_member_ids()
    
    if not member_ids:
        await message.answer("❌ Нет участников.")
        return
    
    success_count = 0
    error_count = 0
    
    for member_id in member_ids:
        try:
