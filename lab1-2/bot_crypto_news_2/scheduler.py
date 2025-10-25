#!/usr/bin/env python3
"""
Планировщик дайджестов
Модуль для автоматической отправки дайджестов пользователям
"""

import asyncio
import schedule
import time
import logging
from datetime import datetime, time as dt_time, timedelta
from typing import Dict, List, Any
import threading

logger = logging.getLogger(__name__)

class DigestScheduler:
    """Класс для планирования отправки дайджестов"""
    
    def __init__(self, bot_instance):
        """Инициализация планировщика"""
        self.bot = bot_instance
        self.running = False
        self.scheduler_thread = None
        
    def start_scheduler(self):
        """Запуск планировщика в отдельном потоке"""
        if self.running:
            logger.warning("Планировщик уже запущен")
            return
        
        self.running = True
        self.scheduler_thread = threading.Thread(target=self._run_scheduler, daemon=True)
        self.scheduler_thread.start()
        logger.info("Планировщик дайджестов запущен")
    
    def stop_scheduler(self):
        """Остановка планировщика"""
        self.running = False
        if self.scheduler_thread:
            self.scheduler_thread.join(timeout=5)
        logger.info("Планировщик дайджестов остановлен")
    
    def _run_scheduler(self):
        """Основной цикл планировщика"""
        while self.running:
            try:
                schedule.run_pending()
                time.sleep(60)  # Проверяем каждую минуту
            except Exception as e:
                logger.error(f"Ошибка в планировщике: {e}")
                time.sleep(60)
    
    def schedule_user_digest(self, user_id: int, user_data: Dict[str, Any]):
        """Планирование дайджеста для конкретного пользователя"""
        if not user_data.get('digest_enabled', False):
            return
        
        digest_time = user_data.get('digest_time', '09:00')
        frequency = user_data.get('digest_frequency', 'daily')
        
        try:
            # Парсим время
            hour, minute = map(int, digest_time.split(':'))
            digest_time_obj = dt_time(hour, minute)
            
            # Удаляем старые задачи для этого пользователя
            self._remove_user_jobs(user_id)
            
            # Добавляем новую задачу в зависимости от частоты
            if frequency == 'daily':
                schedule.every().day.at(digest_time).do(
                    self._send_digest_job, user_id
                ).tag(f"user_{user_id}")
            elif frequency == 'weekly':
                schedule.every().monday.at(digest_time).do(
                    self._send_digest_job, user_id
                ).tag(f"user_{user_id}")
            elif frequency == 'weekdays':
                schedule.every().monday.at(digest_time).do(
                    self._send_digest_job, user_id
                ).tag(f"user_{user_id}")
                schedule.every().tuesday.at(digest_time).do(
                    self._send_digest_job, user_id
                ).tag(f"user_{user_id}")
                schedule.every().wednesday.at(digest_time).do(
                    self._send_digest_job, user_id
                ).tag(f"user_{user_id}")
                schedule.every().thursday.at(digest_time).do(
                    self._send_digest_job, user_id
                ).tag(f"user_{user_id}")
                schedule.every().friday.at(digest_time).do(
                    self._send_digest_job, user_id
                ).tag(f"user_{user_id}")
            
            logger.info(f"Запланирован дайджест для пользователя {user_id}: {frequency} в {digest_time}")
            
        except Exception as e:
            logger.error(f"Ошибка планирования дайджеста для пользователя {user_id}: {e}")
    
    def _remove_user_jobs(self, user_id: int):
        """Удаление всех задач для конкретного пользователя"""
        try:
            schedule.clear(f"user_{user_id}")
        except Exception as e:
            logger.error(f"Ошибка удаления задач для пользователя {user_id}: {e}")
    
    def _send_digest_job(self, user_id: int):
        """Задача отправки дайджеста"""
        try:
            # Создаем новый event loop для асинхронного вызова
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            # Вызываем асинхронный метод отправки дайджеста
            loop.run_until_complete(self.bot.send_digest(user_id))
            
            loop.close()
            
        except Exception as e:
            logger.error(f"Ошибка отправки дайджеста пользователю {user_id}: {e}")
    
    def update_all_schedules(self):
        """Обновление расписания для всех пользователей"""
        try:
            # Очищаем все задачи
            schedule.clear()
            
            # Планируем дайджесты для всех пользователей
            for user_id_str, user_data in self.bot.users_data.items():
                user_id = int(user_id_str)
                self.schedule_user_digest(user_id, user_data)
            
            logger.info(f"Обновлено расписание для {len(self.bot.users_data)} пользователей")
            
        except Exception as e:
            logger.error(f"Ошибка обновления расписания: {e}")
    
    def get_next_digest_time(self, user_id: int) -> str:
        """Получение времени следующего дайджеста для пользователя"""
        try:
            user_data = self.bot.get_user_data(user_id)
            if not user_data.get('digest_enabled', False):
                return "Дайджест отключен"
            
            digest_time = user_data.get('digest_time', '09:00')
            frequency = user_data.get('digest_frequency', 'daily')
            
            now = datetime.now()
            
            if frequency == 'daily':
                next_time = now.replace(
                    hour=int(digest_time.split(':')[0]),
                    minute=int(digest_time.split(':')[1]),
                    second=0,
                    microsecond=0
                )
                if next_time <= now:
                    next_time += timedelta(days=1)
                    
            elif frequency == 'weekly':
                days_ahead = 7 - now.weekday()  # Понедельник = 0
                if days_ahead == 7:
                    days_ahead = 0
                next_time = now + timedelta(days=days_ahead)
                next_time = next_time.replace(
                    hour=int(digest_time.split(':')[0]),
                    minute=int(digest_time.split(':')[1]),
                    second=0,
                    microsecond=0
                )
                
            elif frequency == 'weekdays':
                days_ahead = 1 - now.weekday()  # Следующий рабочий день
                if days_ahead <= 0:
                    days_ahead += 5
                next_time = now + timedelta(days=days_ahead)
                next_time = next_time.replace(
                    hour=int(digest_time.split(':')[0]),
                    minute=int(digest_time.split(':')[1]),
                    second=0,
                    microsecond=0
                )
            
            return next_time.strftime('%d.%m.%Y %H:%M')
            
        except Exception as e:
            logger.error(f"Ошибка расчета времени следующего дайджеста: {e}")
            return "Ошибка расчета"
    
    def get_scheduled_jobs_count(self) -> int:
        """Получение количества запланированных задач"""
        return len(schedule.jobs)
