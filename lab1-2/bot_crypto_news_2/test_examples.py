#!/usr/bin/env python3
"""
Примеры использования News Aggregator Bot
Демонстрационные скрипты и тесты
"""

import os
import json
import asyncio
from datetime import datetime
from news_utils import NewsFetcher, NewsFilter, NewsFormatter

def test_news_fetcher():
    """Тестирование получения новостей"""
    print("🔍 Тестирование NewsFetcher...")
    
    fetcher = NewsFetcher()
    
    # Тест RSS новостей
    print("\n📡 Тестирование RSS новостей:")
    rss_news = fetcher.fetch_rss_news('ru', 3)
    for i, news in enumerate(rss_news, 1):
        print(f"{i}. {news['title']}")
        print(f"   📅 {news['date']}")
        print(f"   🔗 {news['url']}")
        print()
    
    # Тест фильтрации по темам
    print("\n🔍 Тестирование фильтрации по темам:")
    topics = ['технологии', 'IT', 'программирование']
    filtered_news = fetcher.get_news_by_topics(topics, 'ru', 3)
    for i, news in enumerate(filtered_news, 1):
        print(f"{i}. {news['title']}")
        print(f"   📅 {news['date']}")
        print()

def test_news_filter():
    """Тестирование фильтрации новостей"""
    print("\n🔍 Тестирование NewsFilter...")
    
    filter_obj = NewsFilter()
    
    # Пример новостей
    sample_news = [
        {
            'title': 'Новые технологии в программировании',
            'description': 'Обзор последних тенденций в разработке ПО',
            'date': '01.01.2024 10:00',
            'url': 'https://example.com/news1',
            'source': 'TechNews'
        },
        {
            'title': 'Реклама нового iPhone',
            'description': 'Купите новый iPhone со скидкой 50%',
            'date': '01.01.2024 11:00',
            'url': 'https://example.com/ad1',
            'source': 'AdSite'
        },
        {
            'title': 'Криптовалюты набирают популярность',
            'description': 'Bitcoin достиг новых высот',
            'date': '01.01.2024 12:00',
            'url': 'https://example.com/crypto',
            'source': 'CryptoNews'
        }
    ]
    
    # Фильтрация с исключением рекламы
    filtered = filter_obj.filter_news(sample_news)
    print(f"После фильтрации осталось: {len(filtered)} новостей")
    
    # Удаление дубликатов
    duplicate_news = sample_news + sample_news[:2]
    unique = filter_obj.remove_duplicates(duplicate_news)
    print(f"После удаления дубликатов: {len(unique)} новостей")

def test_news_formatter():
    """Тестирование форматирования новостей"""
    print("\n📝 Тестирование NewsFormatter...")
    
    formatter = NewsFormatter()
    
    sample_news = [
        {
            'title': 'Важная новость дня',
            'description': 'Подробное описание важной новости',
            'date': '01.01.2024 10:00',
            'url': 'https://example.com/important',
            'source': 'ImportantNews'
        },
        {
            'title': 'Технологические новости',
            'description': 'Обзор технологических достижений',
            'date': '01.01.2024 11:00',
            'url': 'https://example.com/tech',
            'source': 'TechNews'
        }
    ]
    
    # Форматирование списка новостей
    formatted_list = formatter.format_news_list(sample_news, 2)
    print("📰 Форматированный список новостей:")
    print(formatted_list)
    
    # Форматирование дайджеста
    formatted_digest = formatter.format_digest(sample_news)
    print("\n📧 Форматированный дайджест:")
    print(formatted_digest)

def create_sample_user_data():
    """Создание примера данных пользователя"""
    print("\n👤 Создание примера данных пользователя...")
    
    sample_data = {
        "123456789": {
            "topics": [
                "технологии",
                "программирование", 
                "искусственный интеллект",
                "криптовалюты"
            ],
            "keywords": ["python", "машинное обучение"],
            "digest_enabled": True,
            "digest_time": "09:00",
            "digest_frequency": "daily",
            "sources": ["rss", "api"],
            "language": "ru",
            "region": "ru",
            "created_at": datetime.now().isoformat()
        }
    }
    
    with open('sample_user_data.json', 'w', encoding='utf-8') as f:
        json.dump(sample_data, f, ensure_ascii=False, indent=2)
    
    print("✅ Пример данных пользователя сохранен в sample_user_data.json")

def test_bot_commands():
    """Демонстрация команд бота"""
    print("\n🤖 Демонстрация команд бота:")
    
    commands = [
        ("/start", "Начать работу с ботом"),
        ("/help", "Показать список команд"),
        ("/top", "Показать топ новостей"),
        ("/digest", "Управление дайджестом"),
        ("/time 09:30", "Установить время дайджеста"),
        ("/freq daily", "Установить ежедневную частоту"),
        ("/sources", "Выбрать источники новостей"),
        ("/lang ru", "Выбрать русский язык"),
        ("/region ru", "Выбрать регион Россия"),
        ("/list", "Показать список тем"),
        ("/remove 1", "Удалить тему номер 1"),
        ("/rename 1 IT новости", "Переименовать тему"),
        ("/about", "Информация о боте")
    ]
    
    for command, description in commands:
        print(f"  {command:<20} - {description}")

def main():
    """Главная функция для запуска тестов"""
    print("🚀 Запуск тестов News Aggregator Bot")
    print("=" * 50)
    
    try:
        # Тестируем компоненты
        test_news_fetcher()
        test_news_filter()
        test_news_formatter()
        create_sample_user_data()
        test_bot_commands()
        
        print("\n✅ Все тесты завершены успешно!")
        print("\n📋 Следующие шаги:")
        print("1. Установите зависимости: pip install -r requirements.txt")
        print("2. Создайте файл .env с токеном бота")
        print("3. Запустите бота: python bot.py")
        
    except Exception as e:
        print(f"\n❌ Ошибка при выполнении тестов: {e}")

if __name__ == '__main__':
    main()
