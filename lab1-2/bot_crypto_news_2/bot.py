#!/usr/bin/env python3
"""
Telegram News Aggregator Bot
Бот-агрегатор новостей с возможностью настройки дайджестов и фильтрации
"""

import os
import json
import logging
import sys
import asyncio
from datetime import datetime, time, timedelta
import re
from typing import Any, Dict, List, Optional
import requests
from telegram.error import TimedOut
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.request import HTTPXRequest
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, 
    MessageHandler, filters, ContextTypes
)
from dotenv import load_dotenv
from news_utils import NewsFetcher, NewsFilter, NewsFormatter
from scheduler import DigestScheduler
from telegram.request import HTTPXRequest
from telegram.error import TimedOut


# Загружаем переменные окружения
load_dotenv()

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

class NewsAggregatorBot:
    """Основной класс бота-агрегатора новостей"""
    
    def __init__(self):
        """Инициализация бота"""
        self.token = os.getenv('TELEGRAM_BOT_TOKEN')
        if not self.token:
            raise ValueError("TELEGRAM_BOT_TOKEN не найден в переменных окружения")
        
        self.data_file = 'bot_data.json'
        self.users_data = self.load_data()
        
        # Инициализация утилит для работы с новостями
        self.news_fetcher = NewsFetcher()
        self.news_filter = NewsFilter()
        self.news_formatter = NewsFormatter()
        
        # Инициализация планировщика
        self.scheduler = DigestScheduler(self)
        
        # Поддерживаемые языки и регионы
        self.supported_languages = ['ru', 'en', 'de', 'fr', 'es']
        self.supported_regions = ['ru', 'us', 'de', 'fr', 'gb', 'ua']
        
    async def _safe_reply(self, update: Update, text: str, **kwargs):
        """Безопасная отправка сообщения с повторами при таймаутах."""
        msg = update.effective_message
        if msg is None:
            return None
        for attempt in range(3):
            try:
                return await msg.reply_text(text, **kwargs)
            except TimedOut:
                await asyncio.sleep(2 ** attempt)  # 1с, 2с, 4с
        # последняя попытка — просто логируем
        try:
            return await msg.reply_text(text, **kwargs)
        except Exception as e:
            logger.warning(f"Не удалось отправить сообщение после повторов: {e}")
            return None

    def _fetch_newsapi_smart_sync(self, user_data: Dict[str, Any], query: str, region: Optional[str]) -> list:
        """Умный поиск NewsAPI: пробуем top-headlines по стране, затем everything по языку, затем фолбэк на us/en.
        Соответствует доке: language не используется в top-headlines, язык только для everything.
        """
        import os, requests

        api_key = os.getenv("NEWSAPI_KEY")
        if not api_key:
            logger.error("[newsapi] NEWSAPI_KEY отсутствует")
            return []

        headers = {"X-Api-Key": api_key}

        # Разрешённые языки NewsAPI для /v2/everything
        allowed_lang = {"ar","de","en","es","fr","he","it","nl","no","pt","ru","sv","ud","zh"}

        # Маппинг страна->предпочтительный язык для everything (минимальный)
        region_lang = {
            "ru": "ru", "ua": "ru", "by": "ru",
            "us": "en", "gb": "en", "ca": "en", "au": "en",
            "de": "de", "fr": "fr", "es": "es", "it": "it",
            "nl": "nl", "pt": "pt", "no": "no", "se": "sv",
            "cn": "zh", "jp": "en", "kr": "en",
        }

        user_lang = (user_data.get("language") or "").lower()
        if user_lang not in allowed_lang:
            user_lang = "en"

        def call_top(country: str) -> list:
            url = "https://newsapi.org/v2/top-headlines"
            params = {"country": country, "pageSize": 5}
            if query:
                params["q"] = query
            try:
                r = requests.get(url, params=params, headers=headers, timeout=10)
                j = {}
                try:
                    j = r.json()
                except Exception:
                    pass
                logger.info("[newsapi] top %s -> %s; total=%s", country, r.status_code, j.get("totalResults"))
                if r.status_code == 429:
                    logger.error("[newsapi] rate-limit on top-headlines")
                    return []
                if r.ok and j.get("status") == "ok":
                    return j.get("articles") or []
            except Exception as e:
                logger.error("[newsapi] top exception: %s", e)
            return []

        def call_everything(lang: str) -> list:
            if lang not in allowed_lang:
                lang = "en"
            url = "https://newsapi.org/v2/everything"
            params = {"language": lang, "pageSize": 5, "q": query}
            try:
                r = requests.get(url, params=params, headers=headers, timeout=10)
                j = {}
                try:
                    j = r.json()
                except Exception:
                    pass
                logger.info("[newsapi] everything %s -> %s; total=%s", lang, r.status_code, j.get("totalResults"))
                if r.status_code == 429:
                    logger.error("[newsapi] rate-limit on everything")
                    return []
                if r.ok and j.get("status") == "ok":
                    return j.get("articles") or []
            except Exception as e:
                logger.error("[newsapi] everything exception: %s", e)
            return []

        # --- Логика выбора ---
        # Если указан регион: пробуем top-headlines по стране, затем everything по языку региона,
        # затем запасные us/en
        if region and len(region) == 2:
            reg = region.lower()
            arts = call_top(reg)
            if arts:
                return arts

            lang = region_lang.get(reg, user_lang)
            arts = call_everything(lang)
            if arts:
                return arts

            if reg != "us":
                arts = call_top("us")
                if arts:
                    return arts
            if lang != "en":
                arts = call_everything("en")
                if arts:
                    return arts
            return []

        # Регион не указан: сначала everything по языку пользователя (или en), затем запасные
        arts = call_everything(user_lang)
        if arts:
            return arts
        arts = call_everything("en")
        if arts:
            return arts
        return call_top("us")

    
    async def error_handler(self, update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Глобальный обработчик ошибок PTB."""
        err = context.error
        if isinstance(err, TimedOut):
            logger.warning("⏱️ Telegram API timeout — операция проигнорирована.")
            return
        logger.exception("Необработанная ошибка бота: %s", err)

    
    def load_data(self) -> Dict[str, Any]:
        """Загрузка данных пользователей из JSON файла"""
        try:
            if os.path.exists(self.data_file):
                with open(self.data_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            return {}
        except Exception as e:
            logger.error(f"Ошибка загрузки данных: {e}")
            return {}
    
    def save_data(self) -> None:
        """Сохранение данных пользователей в JSON файл"""
        try:
            with open(self.data_file, 'w', encoding='utf-8') as f:
                json.dump(self.users_data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Ошибка сохранения данных: {e}")
    
    def get_user_data(self, user_id: int) -> Dict[str, Any]:
        """Получение данных пользователя"""
        if str(user_id) not in self.users_data:
            self.users_data[str(user_id)] = {
                'topics': [],
                'keywords': [],
                'digest_enabled': False,
                'digest_time': '09:00',
                'digest_frequency': 'daily',
                'sources': ['rss'],
                'language': 'ru',
                'region': 'ru',
                'created_at': datetime.now().isoformat()
            }
            self.save_data()
        return self.users_data[str(user_id)]
    
    def update_user_data(self, user_id: int, data: Dict[str, Any]) -> None:
        """Обновление данных пользователя"""
        self.users_data[str(user_id)].update(data)
        self.save_data()
        
        # Обновляем расписание дайджеста если изменились настройки
        if any(key in data for key in ['digest_enabled', 'digest_time', 'digest_frequency']):
            user_data = self.get_user_data(user_id)
            self.scheduler.schedule_user_digest(user_id, user_data)
    
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Обработчик команды /start"""
        user_id = update.effective_user.id
        user_data = self.get_user_data(user_id)
        
        welcome_message = (
            "📰 Добро пожаловать в News Aggregator Bot!\n\n"
            "Я помогу вам собирать и фильтровать новости по интересующим темам.\n\n"
            "Основные возможности:\n"
            "• 📊 Топ новостей за день\n"
            "• 📧 Ежедневные дайджесты\n"
            "• 🔍 Фильтрация по ключевым словам\n"
            "• 🌍 Настройка источников и регионов\n\n"
            "Используйте /help для просмотра всех команд."
        )
        
        await self._safe_reply(update,welcome_message)
    
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Обработчик команды /help"""
        help_text = (
            "📋 Список команд:\n\n"
            "🚀 /start — запуск и приветствие\n"
            "📋 /help — эта справка\n"
            "🗞️ /news — топ-5 новостей по теме: /news <тема>\n"
            "🔎 /search — поиск по сохранённым темам: /search <слова>\n"
            "🧩 /topic — управление темами: add | list | remove | rename\n"
            "📝 /list — показать список всех тем\n"
            "💾 /save — сохранить новость: /save <номер|url> (из последней выдачи)\n"
            "📚 /saved — показать сохранённые материалы\n"
            "📊 /top — показать топ новостей за день\n"
            "💱 /crypto_usdt — курс USDT (Tether) с 24h change\n"
            "📧 /digest — включить/выключить ежедневный дайджест\n"
            "⏰ /time — задать время отправки дайджеста\n"
            "📅 /freq — выбрать частоту дайджеста (daily | weekly | weekdays)\n"
            "📡 /sources — выбрать источники новостей\n"
            "🌐 /lang — выбрать язык новостей (ru/en/…)\n"
            "🌍 /region — задать географический регион (ru/us/de/…)\n"
            "ℹ️ /about — информация о боте\n\n"
            "Примеры использования:\n"
            "• /news bitcoin — показать свежие новости про Bitcoin\n"
            "• /topic add ИИ — добавить тему «ИИ»\n"
            "• /save 3 — сохранить новость №3 из последней выдачи\n"
            "• /time 09:30 — установить время дайджеста на 09:30\n"
            "• /freq weekly — получать дайджест еженедельно\n"
            "• /lang en — переключиться на английский язык\n"
            "• /crypto_usdt — получить текущий курс USDT\n"
        )

        
        await self._safe_reply(update,help_text)
    
    
    async def topic_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Обработчик команды /topic — управление темами (добавление, список, удаление, переименование)."""
        user_id = update.effective_user.id
        user_data = self.get_user_data(user_id)
        args = context.args or []
        
        def normalize_name(name: str) -> str:
            return " ".join(name.split()).strip()
        
        async def show_usage():
            await self._safe_reply(update,
                "🧩 Управление темами\n\n"
                "Добавить тему:\n"
                "• /topic <название>\n"
                "• /topic add <название>\n\n"
                "Список тем:\n"
                "• /topic list\n\n"
                "Удалить тему:\n"
                "• /topic remove <номер|название>\n\n"
                "Переименовать тему:\n"
                "• /topic rename <номер> <новое название>"
            )
        
        if not args:
            await show_usage()
            return
        
        sub = args[0].lower()
        
        if sub in ("list", "ls", "show"):
            topics = user_data.get("topics", [])
            if not topics:
                await self._safe_reply(update, "Список тем пуст. Добавьте тему: /topic <название>")
                return
            lines = [f"{i+1}. {t}" for i, t in enumerate(topics)]
            await self._safe_reply(update, "📚 Ваши темы:\n" + "\n".join(lines))
            return
        
        if sub in ("remove", "rm", "del", "delete"):
            if len(args) < 2:
                await self._safe_reply(update, "Укажите номер или название темы. Пример: /topic remove 2")
                return
            target = " ".join(args[1:])
            topics = user_data.get("topics", [])
            removed = None
            try:
                idx = int(target) - 1
                if 0 <= idx < len(topics):
                    removed = topics.pop(idx)
            except ValueError:
                norm = target.strip().lower()
                for i, t in enumerate(topics):
                    if t.lower() == norm:
                        removed = topics.pop(i)
                        break
            if removed is None:
                await self._safe_reply(update, "Тема не найдена.")
                return
            self.update_user_data(user_id, {"topics": topics})
            await self._safe_reply(update, f"🗑️ Тема удалена: {removed}")
            return
        
        if sub in ("rename", "mv"):
            if len(args) < 3:
                await self._safe_reply(update, "Укажите номер темы и новое название. Пример: /topic rename 1 Генетика")
                return
            try:
                idx = int(args[1]) - 1
            except ValueError:
                await self._safe_reply(update, "Первый аргумент должен быть номером темы. Пример: /topic rename 1 Генетика")
                return
            topics = user_data.get("topics", [])
            if not (0 <= idx < len(topics)):
                await self._safe_reply(update, "Некорректный номер темы.")
                return
            new_name = normalize_name(" ".join(args[2:]))
            if not new_name:
                await self._safe_reply(update, "Новое название темы не может быть пустым.")
                return
            if any(t.lower() == new_name.lower() for t in topics):
                await self._safe_reply(update, "Такая тема уже существует.")
                return
            old_name = topics[idx]
            topics[idx] = new_name
            self.update_user_data(user_id, {"topics": topics})
            await self._safe_reply(update, f"✏️ Тема переименована: «{old_name}» → «{new_name}»")
            return
        
        if sub == "add":
            name = normalize_name(" ".join(args[1:]))
        else:
            name = normalize_name(" ".join(args))
        
        if not name:
            await self._safe_reply(update, "Укажите название темы. Пример: /topic Машинное обучение")
            return
        
        topics = user_data.get("topics", [])
        if len(topics) >= 100:
            await self._safe_reply(update, "Достигнут лимит из 100 тем. Удалите лишние: /topic list")
            return
        if any(t.lower() == name.lower() for t in topics):
            await self._safe_reply(update, "Такая тема уже есть. Посмотреть список: /topic list")
            return
        
        topics.append(name)
        self.update_user_data(user_id, {"topics": topics})
        await self._safe_reply(update, f"✅ Тема добавлена: {name}")
    
    
    async def save_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Сохранить новость: /save <номер> или /save <url> (из последней выдачи)."""
        user_id = update.effective_user.id
        user_data = self.get_user_data(user_id)
        saved = user_data.get("saved", [])
        args = context.args or []
        if not args:
            await self._safe_reply(update, "Укажи номер или URL: /save 2  или  /save https://example.com/news")
            return
        target = " ".join(args)
        # как URL
        if target.startswith("http://") or target.startswith("https://"):
            item = {"title": target, "url": target, "date": datetime.now().strftime("%d.%m.%Y %H:%M"), "source": "manual"}
            saved.append(item)
            self.update_user_data(user_id, {"saved": saved})
            await self._safe_reply(update, "💾 Сохранено.")
            return
        # как индекс
        try:
            idx = int(target) - 1
        except ValueError:
            await self._safe_reply(update, "Неверный аргумент. Укажи номер новости или URL.")
            return
        last_news = context.user_data.get("last_news", [])
        if not (0 <= idx < len(last_news)):
            await self._safe_reply(update, "Нет такой позиции в последней выдаче.")
            return
        saved.append(last_news[idx])
        self.update_user_data(user_id, {"saved": saved})
        await self._safe_reply(update, f"💾 Сохранено: {last_news[idx].get('title','(без названия)')}")
    
    async def saved_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Показать сохранённые материалы."""
        user_id = update.effective_user.id
        user_data = self.get_user_data(user_id)
        saved = user_data.get("saved", [])
        if not saved:
            await self._safe_reply(update, "📚 У тебя нет сохранённых материалов.")
            return
        lines = []
        for i, it in enumerate(saved, 1):
            t = it.get("title") or "(без названия)"
            u = it.get("url") or ""
            d = it.get("date") or ""
            s = it.get("source") or ""
            lines.append(f"{i}. {t}\n{u}\n{d} • {s}")
        await self._safe_reply(update, "📚 Сохранённые материалы:\n\n" + "\n\n".join(lines))
    
    async def search_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Ищет новости по ТЕМАМ (пер- тема, не просто фильтр топа)."""
        user_id = update.effective_user.id
        user_data = self.get_user_data(user_id)
        topics = [t.strip() for t in user_data.get("topics", []) if t.strip()]
        if not topics:
            await self._safe_reply(update, "Сначала добавь темы: /topic <название>")
            return
        
                # Собираем новости из выбранных источников (без топик-фильтра на этом шаге)
        lang = user_data.get('language', 'ru')
        region = user_data.get('region', 'ru')
        sources = user_data.get('sources', ['rss'])

        all_news = []

        if 'rss' in sources:
            # Подними лимит, чтобы /search нашёл больше совпадений
            all_news.extend(self.news_fetcher.fetch_rss_news(lang, 50))

        if 'api' in sources:
            all_news.extend(self.news_fetcher.fetch_api_news(lang, region, 50))
            all_news.extend(self.news_fetcher.fetch_mediastack_news(lang, region, 50))

        # Дедуп перед тематической фильтрацией
        all_news = self.news_filter.remove_duplicates(all_news)
        logger.info(all_news)

        if not all_news:
            await self._safe_reply(update, "Пока не удалось получить новости из источников.")
            return


        # all_news = await self.news_fetcher.fetch(
        #     feeds=user_data.get('sources', ['rss']),
        #     language=user_data.get('language', 'ru'),
        #     region=user_data.get('region', 'ru'),
        #     limit=200
        # )
        # if not all_news:
        #     await self._safe_reply(update, "Пока не удалось получить новости из источников.")
        #     return
        groups = []
        for t in topics:
            filtered = self.news_filter.filter_news(all_news, keywords=[t])
            if filtered:
                groups.append((t, filtered[:5]))
        if not groups:
            await self._safe_reply(update, "🕵️ По твоим темам свежих новостей не найдено.")
            return
        flat = [it for _, lst in groups for it in lst]
        context.user_data["last_news"] = flat
        chunks = []
        for topic, lst in groups:
            header = f"🔎 {topic}"
            block_lines = []
            for i, it in enumerate(lst, 1):
                title = it.get("title") or "(без названия)"
                url = it.get("url") or ""
                date = it.get("date") or ""
                src  = it.get("source") or ""
                block_lines.append(f"{i}. {title}\n{url}\n{date} • {src}")
            chunks.append(header + "\n" + "\n".join(block_lines))
        msg = "\n\n".join(chunks)
        await self._safe_reply(update, msg)
    
    async def crypto_usdt_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Команда /crypto_usdt — получить текущий курс USDT (Tether) из CoinGecko."""
        try:
            data = await asyncio.get_event_loop().run_in_executor(None, self._fetch_usdt_price_sync)
            if not data:
                await self._safe_reply(update, "Не удалось получить данные о курсе USDT.")
                return
            usd = data.get("usd")
            eur = data.get("eur")
            rub = data.get("rub")
            chg = data.get("usd_24h_change")
            ts  = data.get("last_updated_at")
            dt_str = datetime.utcfromtimestamp(ts).strftime("%d.%m.%Y %H:%M") + " UTC" if ts else ""
            chg_str = ""
            if isinstance(chg, (int, float)):
                sign = "📈" if chg >= 0 else "📉"
                chg_str = f"\n24ч: {sign} {chg:.2f}%"
            lines = ["💱 Курс USDT (CoinGecko)"]
            if usd is not None: lines.append(f"USD: {usd}")
            if eur is not None: lines.append(f"EUR: {eur}")
            if rub is not None: lines.append(f"RUB: {rub}")
            if dt_str: lines.append(f"Обновлено: {dt_str}")
            msg = "\n".join(lines) + chg_str
            await self._safe_reply(update, msg)
        except Exception as e:
            logger.exception("Ошибка в /crypto_usdt: %s", e)
            await self._safe_reply(update, "Ошибка при запросе курса USDT.")
    
    def _fetch_usdt_price_sync(self) -> Optional[dict]:
        """Синхронный запрос в CoinGecko Simple Price. Возвращает словарь с полями usd/eur/rub и метаданными."""
        import os, requests
        api_key = os.getenv("COINGECKO_API_KEY")  # опционально
        if api_key:
            logger.info("API key exists")
            url = "https://api.coingecko.com/api/v3/simple/price"
            headers = {"x-cg-demo-api-key": api_key}
        else:
            url = "https://api.coingecko.com/api/v3/simple/price"
            headers = {}
        params = {
            "ids": "tether",
            "vs_currencies": "usd,eur,rub",
            "include_24hr_change": "true",
            "include_last_updated_at": "true",
        }
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=10)
            resp.raise_for_status()
            j = resp.json()
            t = j.get("tether") or {}
            out = {
                "usd": t.get("usd"),
                "eur": t.get("eur"),
                "rub": t.get("rub"),
                "usd_24h_change": t.get("usd_24h_change"),
                "last_updated_at": t.get("last_updated_at"),
            }
            return out
        except Exception as e:
            logger.error(f"CoinGecko запрос не удался: {e}")
            return None

    
    
    async def news_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Команда /news — топ-5 через NewsAPI. Формат: /news <запрос> [<регион-ISO2>].
        Пример: /news ИИ us  | /news экономика ru
        Если в регионе ru нет выдачи, будет предпринят поиск в другом регионе/языке.
        """
        user_id = update.effective_user.id
        user_data = self.get_user_data(user_id)
        args = context.args or []
        if not args:
            hint = (
                "📰 Как использовать /news:\n"
                "• /news <запрос> — поиск по теме (язык берётся из настроек, иначе en)\n"
                "• /news <запрос> <регион-ISO2> — страна новостей, напр.: us, gb, de, ru\n"
                "Примеры:\n"
                "  /news искусственный интеллект us\n"
                "  /news экономика ru\n"
                "  /news sport\n"
                "Если в регионе ru пусто, бот попробует другой регион/язык."
            )
            await self._safe_reply(update, hint)
            return
        # Парсим: если последний токен выглядит как ISO2 — считаем это регионом
        region = None
        if len(args) >= 2 and re.fullmatch(r"[A-Za-z]{2}", args[-1]):
            region = args[-1].lower()
            query = " ".join(args[:-1])
        else:
            query = " ".join(args)
        if not query.strip():
            await self._safe_reply(update, "Укажи тему поиска: /news <запрос> [<регион-ISO2>]")
            return
        try:
            articles = await asyncio.get_event_loop().run_in_executor(
                None, self._fetch_newsapi_smart_sync, user_data, query, region
            )
            if not articles:
                await self._safe_reply(update, "📰 Ничего не найдено (или сервис недоступен). Попробуй другой регион, например: /news {q} us".format(q=query))
                return
            # Сохраняем для /save N
            context.user_data["last_news"] = articles
            lines = []
            for i, a in enumerate(articles[:5], 1):
                title = a.get("title") or "(без названия)"
                url   = a.get("url") or ""
                src   = (a.get("source") or {}).get("name") or ""
                date  = a.get("publishedAt") or ""
                lines.append(f"{i}. {title}\n{url}\n{date} • {src}")
            await self._safe_reply(update, "📰 Топ-5 новостей (NewsAPI):\n\n" + "\n\n".join(lines))
        except Exception as e:
            logger.exception("Ошибка в /news: %s", e)
            await self._safe_reply(update, "Ошибка при запросе новостей.")
    

    async def about_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Обработчик команды /about"""
        about_text = (
            "🤖 News Aggregator Bot v1.0\n\n"
            "Создатель: Daniil Korinenko\n"
            "Университет: МАГА, 3 семестр\n"
            "Курс: Основы web-разработки\n\n"
            "Этот бот собирает новости из различных источников,\n"
            "фильтрует их по вашим интересам и отправляет\n"
            "персонализированные дайджесты.\n\n"
            "Технологии:\n"
            "• Python 3.8+\n"
            "• python-telegram-bot\n"
            "• JSON для хранения данных\n"
            "• RSS и News API для получения новостей"
        )
        
        await self._safe_reply(update,about_text)
    
    async def top_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Обработчик команды /top - показать топ новостей"""
        user_id = update.effective_user.id
        user_data = self.get_user_data(user_id)
        
        try:
            # Получаем новости (заглушка для демонстрации)
            news = await self.fetch_news(user_data)
            context.user_data['last_news'] = news
            
            if not news:
                await self._safe_reply(update,"📰 Новости не найдены. Попробуйте настроить источники командой /sources")
                return
            
            # Форматируем новости для отправки
            message = self.news_formatter.format_news_list(news, 5)
            await self._safe_reply(update,message)
            
        except Exception as e:
            logger.error(f"Ошибка получения новостей: {e}")
            await self._safe_reply(update,"❌ Произошла ошибка при получении новостей. Попробуйте позже.")
    
    async def digest_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Обработчик команды /digest - управление дайджестом"""
        user_id = update.effective_user.id
        user_data = self.get_user_data(user_id)
        
        # Создаем клавиатуру для переключения дайджеста
        keyboard = [
            [
                InlineKeyboardButton(
                    "✅ Включить" if not user_data['digest_enabled'] else "❌ Выключить",
                    callback_data=f"toggle_digest_{user_id}"
                )
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        status_text = "включен" if user_data['digest_enabled'] else "выключен"
        message = (
            f"📧 Статус дайджеста: {status_text}\n\n"
            f"⏰ Время отправки: {user_data['digest_time']}\n"
            f"📅 Частота: {user_data['digest_frequency']}\n\n"
            "Нажмите кнопку для изменения статуса:"
        )
        
        await self._safe_reply(update,message, reply_markup=reply_markup)
    
    async def time_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Обработчик команды /time - установка времени дайджеста"""
        user_id = update.effective_user.id
        
        if not context.args:
            await self._safe_reply(update,
                "⏰ Укажите время в формате ЧЧ:ММ\n"
                "Пример: /time 09:30"
            )
            return
        
        try:
            time_str = context.args[0]
            # Проверяем формат времени
            time_obj = datetime.strptime(time_str, '%H:%M').time()
            
            self.update_user_data(user_id, {'digest_time': time_str})
            
            await self._safe_reply(update,
                f"✅ Время дайджеста установлено на {time_str}"
            )
            
        except ValueError:
            await self._safe_reply(update,
                "❌ Неверный формат времени. Используйте ЧЧ:ММ (например, 09:30)"
            )
    
    async def freq_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Обработчик команды /freq - установка частоты дайджеста"""
        user_id = update.effective_user.id
        
        if not context.args:
            # Показываем доступные варианты
            keyboard = [
                [InlineKeyboardButton("📅 Ежедневно", callback_data=f"freq_daily_{user_id}")],
                [InlineKeyboardButton("📆 Еженедельно", callback_data=f"freq_weekly_{user_id}")],
                [InlineKeyboardButton("💼 По будням", callback_data=f"freq_weekdays_{user_id}")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await self._safe_reply(update,
                "📅 Выберите частоту дайджеста:",
                reply_markup=reply_markup
            )
            return
        
        frequency = context.args[0].lower()
        valid_frequencies = ['daily', 'weekly', 'weekdays']
        
        if frequency not in valid_frequencies:
            await self._safe_reply(update,
                "❌ Неверная частота. Доступные варианты: daily, weekly, weekdays"
            )
            return
        
        self.update_user_data(user_id, {'digest_frequency': frequency})
        
        freq_names = {
            'daily': 'ежедневно',
            'weekly': 'еженедельно', 
            'weekdays': 'по будням'
        }
        
        await self._safe_reply(update,
            f"✅ Частота дайджеста установлена: {freq_names[frequency]}"
        )
    
    async def sources_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Обработчик команды /sources - выбор источников новостей"""
        user_id = update.effective_user.id
        user_data = self.get_user_data(user_id)
        
        keyboard = []
        available_sources = ['rss', 'api', 'telegram', 'reddit']
        
        for source in available_sources:
            is_selected = source in user_data['sources']
            button_text = f"{'✅' if is_selected else '❌'} {source.upper()}"
            keyboard.append([
                InlineKeyboardButton(
                    button_text,
                    callback_data=f"toggle_source_{source}_{user_id}"
                )
            ])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await self._safe_reply(update,
            "📡 Выберите источники новостей:",
            reply_markup=reply_markup
        )
    
    async def lang_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Обработчик команды /lang - выбор языка новостей"""
        user_id = update.effective_user.id
        
        keyboard = []
        for lang in self.supported_languages:
            keyboard.append([
                InlineKeyboardButton(
                    f"🌐 {lang.upper()}",
                    callback_data=f"set_lang_{lang}_{user_id}"
                )
            ])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await self._safe_reply(update,
            "🌐 Выберите язык новостей:",
            reply_markup=reply_markup
        )
    
    async def region_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Обработчик команды /region - выбор региона"""
        user_id = update.effective_user.id
        
        keyboard = []
        region_names = {
            'ru': '🇷🇺 Россия',
            'us': '🇺🇸 США', 
            'de': '🇩🇪 Германия',
            'fr': '🇫🇷 Франция',
            'gb': '🇬🇧 Великобритания',
            'ua': '🇺🇦 Украина'
        }
        
        for region in self.supported_regions:
            keyboard.append([
                InlineKeyboardButton(
                    region_names.get(region, region.upper()),
                    callback_data=f"set_region_{region}_{user_id}"
                )
            ])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await self._safe_reply(update,
            "🌍 Выберите регион:",
            reply_markup=reply_markup
        )
    
    async def list_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Обработчик команды /list - показать список тем"""
        user_id = update.effective_user.id
        user_data = self.get_user_data(user_id)
        
        if not user_data['topics']:
            await self._safe_reply(update,
                "📝 У вас пока нет сохраненных тем.\n"
                "Добавьте темы, отправив сообщение с интересующими вас темами."
            )
            return
        
        message = "📝 Ваши сохраненные темы:\n\n"
        for i, topic in enumerate(user_data['topics'], 1):
            message += f"{i}. {topic}\n"
        
        await self._safe_reply(update,message)
    
    async def remove_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Обработчик команды /remove - удаление темы"""
        user_id = update.effective_user.id
        user_data = self.get_user_data(user_id)
        
        if not context.args:
            await self._safe_reply(update,
                "🗑️ Укажите номер темы для удаления\n"
                "Пример: /remove 1"
            )
            return
        
        try:
            topic_index = int(context.args[0]) - 1
            if 0 <= topic_index < len(user_data['topics']):
                removed_topic = user_data['topics'].pop(topic_index)
                self.update_user_data(user_id, {'topics': user_data['topics']})
                await self._safe_reply(update,f"✅ Тема '{removed_topic}' удалена")
            else:
                await self._safe_reply(update,"❌ Неверный номер темы")
        except ValueError:
            await self._safe_reply(update,"❌ Укажите корректный номер темы")
    
    async def rename_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Обработчик команды /rename - переименование темы"""
        user_id = update.effective_user.id
        user_data = self.get_user_data(user_id)
        
        if len(context.args) < 2:
            await self._safe_reply(update,
                "✏️ Укажите номер темы и новое название\n"
                "Пример: /rename 1 Новое название"
            )
            return
        
        try:
            topic_index = int(context.args[0]) - 1
            new_name = ' '.join(context.args[1:])
            
            if 0 <= topic_index < len(user_data['topics']):
                old_name = user_data['topics'][topic_index]
                user_data['topics'][topic_index] = new_name
                self.update_user_data(user_id, {'topics': user_data['topics']})
                await self._safe_reply(update,
                    f"✅ Тема '{old_name}' переименована в '{new_name}'"
                )
            else:
                await self._safe_reply(update,"❌ Неверный номер темы")
        except ValueError:
            await self._safe_reply(update,"❌ Укажите корректный номер темы")
    
    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Обработчик обычных сообщений - добавление тем"""
        user_id = update.effective_user.id
        user_data = self.get_user_data(user_id)
        
        message_text = update.message.text.strip()
        
        # Добавляем тему в список
        if message_text not in user_data['topics']:
            user_data['topics'].append(message_text)
            self.update_user_data(user_id, {'topics': user_data['topics']})
            
            await self._safe_reply(update,
                f"✅ Тема '{message_text}' добавлена в ваш список!\n"
                f"Всего тем: {len(user_data['topics'])}"
            )
        else:
            await self._safe_reply(update,
                f"ℹ️ Тема '{message_text}' уже есть в вашем списке"
            )
    
    async def handle_callback_query(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Обработчик callback запросов от inline кнопок"""
        query = update.callback_query
        await query.answer()
        
        data = query.data
        user_id = update.effective_user.id
        
        try:
            if data.startswith('toggle_digest_'):
                # Переключение дайджеста
                user_data = self.get_user_data(user_id)
                user_data['digest_enabled'] = not user_data['digest_enabled']
                self.update_user_data(user_id, {'digest_enabled': user_data['digest_enabled']})
                
                status = "включен" if user_data['digest_enabled'] else "выключен"
                await query.edit_message_text(f"📧 Дайджест {status}")
                
            elif data.startswith('freq_'):
                # Установка частоты
                freq_type = data.split('_')[1]
                self.update_user_data(user_id, {'digest_frequency': freq_type})
                
                freq_names = {
                    'daily': 'ежедневно',
                    'weekly': 'еженедельно',
                    'weekdays': 'по будням'
                }
                
                await query.edit_message_text(
                    f"✅ Частота дайджеста установлена: {freq_names[freq_type]}"
                )
                
            elif data.startswith('toggle_source_'):
                # Переключение источника
                source = data.split('_')[2]
                user_data = self.get_user_data(user_id)
                
                if source in user_data['sources']:
                    user_data['sources'].remove(source)
                else:
                    user_data['sources'].append(source)
                
                self.update_user_data(user_id, {'sources': user_data['sources']})
                
                await query.edit_message_text(f"📡 Источник {source.upper()} {'включен' if source in user_data['sources'] else 'выключен'}")
                
            elif data.startswith('set_lang_'):
                # Установка языка
                lang = data.split('_')[2]
                self.update_user_data(user_id, {'language': lang})
                await query.edit_message_text(f"🌐 Язык установлен: {lang.upper()}")
                
            elif data.startswith('set_region_'):
                # Установка региона
                region = data.split('_')[2]
                self.update_user_data(user_id, {'region': region})
                await query.edit_message_text(f"🌍 Регион установлен: {region.upper()}")
                
        except Exception as e:
            logger.error(f"Ошибка обработки callback: {e}")
            await query.edit_message_text("❌ Произошла ошибка при обработке запроса")
        # Сохранение из inline-кнопки
        if data.startswith("save|"):
            url = data.split("|", 1)[1]
            user_id = query.from_user.id
            user_data = self.get_user_data(user_id)
            saved = user_data.get("saved", [])
            last_list = context.user_data.get("last_news", [])
            item = next((it for it in last_list if it.get("url")==url), {"title": url, "url": url, "date": datetime.now().strftime("%d.%m.%Y %H:%M"), "source":"unknown"})
            saved.append(item)
            self.update_user_data(user_id, {"saved": saved})
            await query.answer("Сохранено")
            return

    
    async def fetch_news(self, user_data: Dict[str, Any]) -> List[Dict[str, str]]:
        """Получение новостей из источников"""
        try:
            all_news = []
            topics = user_data.get('topics', [])
            print("LOG:: here are topics:", topics)
            language = user_data.get('language', 'ru')
            region = user_data.get('region', 'ru')
            sources = user_data.get('sources', ['rss'])
            
            # Получаем новости из разных источников
            if 'rss' in sources:
                rss_news = self.news_fetcher.fetch_rss_news(language, 10)
                all_news.extend(rss_news)
                print("LOG:: we are here in fetch_news with rss:", topics)
            
            if 'api' in sources:
                api_news = self.news_fetcher.fetch_api_news(language, region, 10)
                all_news.extend(api_news)
                
                mediastack_news = self.news_fetcher.fetch_mediastack_news(language, region, 10)
                all_news.extend(mediastack_news)
                print("LOG:: we are here in fetch_news with api:", topics)
            
            # Фильтруем по темам если они есть
            if topics:
                print("LOG:: we are here in fetch_news with topics:", topics)
                filtered_news = self.news_fetcher.get_news_by_topics(topics, language, 15)
                all_news.extend(filtered_news)
            
            # Удаляем дубликаты и фильтруем
            unique_news = self.news_filter.remove_duplicates(all_news)
            final_news = self.news_filter.filter_news(unique_news)
            
            return final_news[:10]  # Возвращаем максимум 10 новостей
            
        except Exception as e:
            logger.error(f"Ошибка получения новостей: {e}")
            return []
    
    async def send_digest(self, user_id: int) -> None:
        """Отправка дайджеста пользователю"""
        try:
            user_data = self.get_user_data(user_id)
            if not user_data['digest_enabled']:
                return
            
            news = await self.fetch_news(user_data)
            context.user_data['last_news'] = news
            
            if not news:
                return
            
            # Форматируем дайджест
            message = self.news_formatter.format_digest(news)
            
            # Здесь должен быть код отправки сообщения пользователю
            # Для демонстрации просто логируем
            logger.info(f"Отправка дайджеста пользователю {user_id}: {len(news)} новостей")
            
        except Exception as e:
            logger.error(f"Ошибка отправки дайджеста: {e}")
    
    
    async def error_handler(self, update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Глобальный обработчик ошибок PTB."""
        err = context.error
        if isinstance(err, TimedOut):
            logger.warning("⏱️ Telegram API timeout — операция проигнорирована.")
            return
        logger.exception("Необработанная ошибка бота: %s", err)


    def run(self) -> None:
        """Запуск бота"""
        # Создаем приложение
        request = HTTPXRequest(connect_timeout=20, read_timeout=20, write_timeout=20, pool_timeout=20)
        application = Application.builder().token(self.token).request(request).build()
        application.add_error_handler(self.error_handler)

        # Добавляем обработчики команд
        application.add_handler(CommandHandler("start", self.start_command))
        application.add_handler(CommandHandler("help", self.help_command))
        application.add_handler(CommandHandler("about", self.about_command))
        application.add_handler(CommandHandler("topic", self.topic_command))
        application.add_handler(CommandHandler("top", self.top_command))
        application.add_handler(CommandHandler("digest", self.digest_command))
        application.add_handler(CommandHandler("time", self.time_command))
        application.add_handler(CommandHandler("freq", self.freq_command))
        application.add_handler(CommandHandler("sources", self.sources_command))
        application.add_handler(CommandHandler("lang", self.lang_command))
        application.add_handler(CommandHandler("region", self.region_command))
        application.add_handler(CommandHandler("list", self.list_command))
        application.add_handler(CommandHandler("remove", self.remove_command))
        application.add_handler(CommandHandler("rename", self.rename_command))
        application.add_handler(CommandHandler("crypto_usdt", self.crypto_usdt_command))
        application.add_handler(CommandHandler("news", self.news_command))
        application.add_handler(CommandHandler("search", self.search_command))
        application.add_handler(CommandHandler("saved", self.saved_command))
        application.add_handler(CommandHandler("save", self.save_command))
        
        # Добавляем обработчики сообщений и callback запросов
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))
        application.add_handler(CallbackQueryHandler(self.handle_callback_query))
        
        # Запускаем планировщик дайджестов
        self.scheduler.start_scheduler()
        
        # Запускаем бота
        logger.info("Запуск News Aggregator Bot...")
        try:
            # Используем простой запуск без дополнительных параметров
            application.run_polling()
        except KeyboardInterrupt:
            logger.info("Получен сигнал остановки...")
        except Exception as e:
            logger.error(f"Ошибка при запуске бота: {e}")
        finally:
            self.scheduler.stop_scheduler()
            logger.info("Бот остановлен")


def main():
    """Главная функция"""
    try:
        bot = NewsAggregatorBot()
        bot.run()
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}")
        print(f"Ошибка запуска бота: {e}")


if __name__ == '__main__':
    main()
