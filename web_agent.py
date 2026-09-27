import asyncio
import os
import time
from bs4 import BeautifulSoup
from curl_cffi.requests import AsyncSession
from google import genai
from google.genai import types
from pydantic import BaseModel
from aiogram import Bot
from aiohttp import web

# ================= НАСТРОЙКИ =================
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
MY_USER_ID = int(os.getenv("MY_USER_ID", "555693826"))

CHANNELS = [
    "naudalenkebro", "normrabota", "distantsiya", "perevod_rabota", "finder_vc",
    "rueventjob", "theyseeku", "FreelanceBay", "freelancetaverna", "freelancce",
    "GetClient", "zdemvc", "linguohunter", "frelanserr", "dnative_job100",
    "marketing_jobs", "vacanciesbest", "budujobs", "theypaygood"
]

POLL_INTERVAL = 180
# =============================================

client_ai = genai.Client(api_key=GEMINI_API_KEY)
bot = Bot(token=TELEGRAM_BOT_TOKEN)
seen_posts = {ch: set() for ch in CHANNELS}

class JobDecision(BaseModel):
    is_relevant: bool
    title: str
    price: str
    cover_letter: str

SYSTEM_PROMPT = """
Ты — персональный карьерный ассистент переводчика и преподавателя.
Профиль кандидата:
- Переводчик и редактор (французский, английский, русский языки). Художественный, технический, деловой перевод.
- Преподаватель / репетитор английского и французского, подготовка к собеседованиям.
- Музыкант / гитарист (уроки гитары, подбор аккордов, съем партий, сессионная запись).

Твоя задача:
1. Проанализировать текст заявки/вакансии.
2. Если задача не по профилю -> is_relevant = false.
3. Если задача релевантна:
   - title: краткая суть задачи (до 7 слов).
   - price: бюджет или ставка (если нет, "Не указан").
   - cover_letter: уверенный, лаконичный отклик от первого лица (2-3 предложения), закрывающий боли заказчика. Без лишних вступлений и шаблонных фраз.
"""

def analyze_job(text: str) -> JobDecision:
    try:
        response = client_ai.models.generate_content(
            model="gemini-3.8-flash",
            contents=f"Текст заявки:\n{text}",
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                response_mime_type="application/json",
                response_schema=JobDecision,
                temperature=0.2,
            ),
        )
        return JobDecision.model_validate_json(response.text)
    except Exception as e:
        print(f"Ошибка Gemini: {e}")
        return JobDecision(is_relevant=False, title="", price="", cover_letter="")

async def fetch_channel_posts(session: AsyncSession, channel: str, initial: bool = False):
    url = f"https://t.me/s/{channel}"
    try:
        resp = await session.get(url, impersonate="safari15_5", timeout=12)
        if resp.status_code != 200:
            return

        soup = BeautifulSoup(resp.text, "html.parser")
        messages = soup.find_all("div", class_="tgme_widget_message_wrap")

        for msg in messages:
            post_div = msg.find("div", class_="tgme_widget_message")
            if not post_div:
                continue

            post_data = post_div.get("data-post")
            if not post_data:
                continue

            post_id = post_data.split("/")[-1]
            if post_id in seen_posts[channel]:
                continue
            
            seen_posts[channel].add(post_id)

            if initial:
                continue

            text_div = msg.find("div", class_="tgme_widget_message_text")
            if not text_div:
                continue

            text = text_div.get_text(separator="\n").strip()
            if len(text) < 40:
                continue

            print(f"\n🔍 [@{channel}] Найден свежий пост #{post_id}. Анализируем через Gemini...")
            decision = await asyncio.to_thread(analyze_job, text)

            if decision.is_relevant:
                post_link = f"https://t.me/{post_data}"
                message = (
                    f"🎯 <b>Новая заявка: {decision.title}</b>\n"
                    f"💰 <b>Бюджет:</b> {decision.price}\n"
                    f"📍 <b>Источник:</b> <a href='{post_link}'>@{channel}</a>\n\n"
                    f"📝 <b>Готовый отклик (тапни для копирования):</b>\n"
                    f"<code>{decision.cover_letter}</code>"
                )
                try:
                    await bot.send_message(chat_id=MY_USER_ID, text=message, parse_mode="HTML")
                    print(f"✅ Отправлен алерт: {decision.title}")
                except Exception as e:
                    print(f"Ошибка отправки в Telegram: {e}")
    except Exception as e:
        print(f"Ошибка парсинга @{channel}: {e}")

async def monitor_loop():
    print("🚀 Инициализация парсера: прогреваем историю каналов...")
    async with AsyncSession() as session:
        for channel in CHANNELS:
            await fetch_channel_posts(session, channel, initial=True)
            await asyncio.sleep(0.5)

        print(f"\n📡 Мониторинг запущен! Отслеживаем {len(CHANNELS)} каналов.")
        while True:
            await asyncio.sleep(POLL_INTERVAL)
            print(f"[{time.strftime('%H:%M:%S')}] Сканируем каналы на новые посты...")
            for channel in CHANNELS:
                await fetch_channel_posts(session, channel, initial=False)
                await asyncio.sleep(1)

# Healthcheck эндпоинт для Render Web Service
async def handle_ping(request):
    return web.Response(text="Job Hunter is Running 24/7!")

async def main():
    try:
        me = await bot.get_me()
        print(f"🤖 Бот активен: @{me.username}")
    except Exception as e:
        print(f"⚠️ Ошибка авторизации бота: {e}")

    # Запускаем мониторинг в фоне
    asyncio.create_task(monitor_loop())

    # Запускаем веб-сервер для бесплатного тарифа Render
    app = web.Application()
    app.router.add_get("/", handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.getenv("PORT", 10000))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print(f"🌐 HTTP Healthcheck активен на порту {port}")

    while True:
        await asyncio.sleep(3600)

if __name__ == "__main__":
    asyncio.run(main())
