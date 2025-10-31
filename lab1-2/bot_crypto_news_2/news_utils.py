#!/usr/bin/env python3
"""
Утилиты для работы с новостями
Модуль для получения и обработки новостей из различных источников
"""

import requests
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
import json
import os
from urllib.parse import urljoin, urlparse
import xml.etree.ElementTree as ET

logger = logging.getLogger(__name__)

class NewsFetcher:
    """Класс для получения новостей из различных источников"""
    
    def __init__(self):
        """Инициализация с настройками из переменных окружения"""
        self.news_api_key = os.getenv('NEWSAPI_KEY')
        self.mediastack_api_key = os.getenv('MEDIASTACK_API_KEY')
        self.http_timeout = int(os.getenv('HTTP_TIMEOUT', 30))
        
        # RSS источники
        self.rss_feeds = {
            'ru': [
                'https://lenta.ru/rss',
                'https://ria.ru/export/rss2/archive/index.xml',
                'https://www.interfax.ru/rss.asp',
                'https://www.vedomosti.ru/rss/news',
                'https://www.gazeta.ru/export/rss/lenta.xml'
            ],
            'en': [
                'https://feeds.bbci.co.uk/news/rss.xml',
                'https://rss.cnn.com/rss/edition.rss',
                'https://feeds.reuters.com/reuters/topNews',
                'https://feeds.npr.org/1001/rss.xml'
            ]
        }
    
    def fetch_rss_news(self, language: str = 'ru', limit: int = 10) -> List[Dict[str, Any]]:
        """Получение новостей из RSS лент"""
        news_list = []
        
        try:
            feeds = self.rss_feeds.get(language, self.rss_feeds['ru'])
            
            for feed_url in feeds[:3]:  # Ограничиваем количество источников
                try:
                    # Получаем RSS ленту
                    response = requests.get(feed_url, timeout=self.http_timeout)
                    response.raise_for_status()
                    
                    # Парсим XML
                    root = ET.fromstring(response.content)
                    
                    # Определяем namespace для RSS
                    namespaces = {
                        'rss': 'http://purl.org/rss/1.0/',
                        'atom': 'http://www.w3.org/2005/Atom',
                        'dc': 'http://purl.org/dc/elements/1.1/',
                        'content': 'http://purl.org/rss/1.0/modules/content/'
                    }
                    
                    # Ищем элементы новостей
                    items = []
                    
                    # Пробуем разные варианты структуры RSS
                    if root.tag == 'rss':
                        # Стандартный RSS 2.0
                        channel = root.find('channel')
                        if channel is not None:
                            items = channel.findall('item')
                    elif root.tag.endswith('feed'):
                        # Atom feed
                        items = root.findall('atom:entry', namespaces)
                    else:
                        # Пробуем найти элементы напрямую
                        items = root.findall('.//item') or root.findall('.//entry')
                    
                    # Если не нашли через channel, пробуем напрямую
                    if not items:
                        items = root.findall('.//item') or root.findall('.//entry')
                    
                    # Обрабатываем найденные элементы
                    items_to_process = min(len(items), max(1, limit // len(feeds)))
                    
                    for item in items[:items_to_process]:
                        try:
                            news_item = self._parse_rss_item(item, namespaces, feed_url, language)
                            if news_item:
                                news_list.append(news_item)
                        except Exception as e:
                            logger.error(f"Ошибка парсинга элемента RSS: {e}")
                            continue
                            
                except ET.ParseError as e:
                    logger.error(f"Ошибка парсинга XML для {feed_url}: {e}")
                    continue
                except Exception as e:
                    logger.error(f"Ошибка получения RSS {feed_url}: {e}")
                    continue
                    
        except Exception as e:
            logger.error(f"Ошибка получения RSS новостей: {e}")
        
        return news_list[:limit]
    
    def _parse_rss_item(self, item: ET.Element, namespaces: Dict[str, str], feed_url: str, language: str) -> Optional[Dict[str, Any]]:
        """Парсинг отдельного элемента RSS"""
        try:
            # Извлекаем заголовок
            title = None
            title_elem = item.find('title')
            if title_elem is not None:
                title = title_elem.text.strip() if title_elem.text else None
            
            logger.debug(f"Заголовок: {title}")
            
            # Извлекаем описание
            description = None
            desc_elem = item.find('description') or item.find('summary')
            if desc_elem is not None:
                description = desc_elem.text.strip() if desc_elem.text else None
            
            # Извлекаем ссылку
            url = None
            link_elem = item.find('link')
            if link_elem is not None:
                url = link_elem.text.strip() if link_elem.text else None
                # Если ссылка относительная, делаем её абсолютной
                if url and not url.startswith('http'):
                    url = urljoin(feed_url, url)
            
            # Извлекаем дату
            date_str = None
            date_elem = item.find('pubDate') or item.find('published') or item.find('dc:date', namespaces)
            if date_elem is not None:
                date_str = date_elem.text.strip() if date_elem.text else None
            
            # Проверяем, что у нас есть хотя бы заголовок
            if not title:
                return None
            
            result = {
                'title': title,
                'description': description or '',
                'url': url or '',
                'date': self._parse_date(date_str),
                'source': self._extract_domain(feed_url),
                'language': language
            }
            
            return result
            
        except Exception as e:
            logger.error(f"Ошибка парсинга RSS элемента: {e}")
            return None
    
    def fetch_api_news(self, language: str = 'ru', country: str = 'ru', limit: int = 10) -> List[Dict[str, Any]]:
        """Получение новостей через News API"""
        news_list = []
        
        if not self.news_api_key:
            logger.warning("News API ключ не настроен")
            return news_list
        
        try:
            url = 'https://newsapi.org/v2/top-headlines'
            params = {
                'apiKey': self.news_api_key,
                'country': country,
                'language': language,
                'pageSize': limit
            }
            
            response = requests.get(url, params=params, timeout=self.http_timeout)
            response.raise_for_status()
            
            data = response.json()
            
            for article in data.get('articles', []):
                news_item = {
                    'title': article.get('title', 'Без заголовка'),
                    'description': article.get('description', ''),
                    'url': article.get('url', ''),
                    'date': self._parse_date(article.get('publishedAt', '')),
                    'source': article.get('source', {}).get('name', 'Unknown'),
                    'language': language
                }
                news_list.append(news_item)
                
        except Exception as e:
            logger.error(f"Ошибка получения новостей через News API: {e}")
        
        return news_list
    
    def fetch_mediastack_news(self, language: str = 'ru', countries: str = 'ru', limit: int = 10) -> List[Dict[str, Any]]:
        """Получение новостей через Mediastack API"""
        news_list = []
        
        if not self.mediastack_api_key:
            logger.warning("Mediastack API ключ не настроен")
            return news_list
        
        try:
            url = 'http://api.mediastack.com/v1/news'
            params = {
                'access_key': self.mediastack_api_key,
                'languages': language,
                'countries': countries,
                'limit': limit
            }
            
            response = requests.get(url, params=params, timeout=self.http_timeout)
            response.raise_for_status()
            
            data = response.json()
            
            for article in data.get('data', []):
                news_item = {
                    'title': article.get('title', 'Без заголовка'),
                    'description': article.get('description', ''),
                    'url': article.get('url', ''),
                    'date': self._parse_date(article.get('published_at', '')),
                    'source': article.get('source', 'Unknown'),
                    'language': language
                }
                news_list.append(news_item)
                
        except Exception as e:
            logger.error(f"Ошибка получения новостей через Mediastack: {e}")
        
        return news_list
    
    def get_news_by_topics(self, topics: List[str], language: str = 'ru', limit: int = 10) -> List[Dict[str, Any]]:
        """Получение новостей по темам"""
        all_news = []
        
        # Получаем новости из разных источников
        all_news.extend(self.fetch_rss_news(language, limit))
        all_news.extend(self.fetch_api_news(language, 'ru', limit))
        
        # Фильтруем по темам
        filtered_news = []
        for news in all_news:
            title_lower = news['title'].lower()
            description_lower = news.get('description', '').lower()
            
            for topic in topics:
                topic_lower = topic.lower()
                if (topic_lower in title_lower or 
                    topic_lower in description_lower):
                    filtered_news.append(news)
                    break
        
        return filtered_news[:limit]
    
    def _parse_date(self, date_str: str) -> str:
        """Парсинг даты в удобный формат"""
        try:
            if not date_str:
                return datetime.now().strftime('%d.%m.%Y %H:%M')
            
            # Пробуем разные форматы
            formats = [
                '%Y-%m-%dT%H:%M:%SZ',
                '%Y-%m-%dT%H:%M:%S.%fZ',
                '%a, %d %b %Y %H:%M:%S %Z',
                '%Y-%m-%d %H:%M:%S'
            ]
            
            for fmt in formats:
                try:
                    dt = datetime.strptime(date_str, fmt)
                    return dt.strftime('%d.%m.%Y %H:%M')
                except ValueError:
                    continue
            
            return datetime.now().strftime('%d.%m.%Y %H:%M')
            
        except Exception:
            return datetime.now().strftime('%d.%m.%Y %H:%M')
    
    def _extract_domain(self, url: str) -> str:
        """Извлечение домена из URL"""
        try:
            parsed = urlparse(url)
            domain = parsed.netloc
            if domain.startswith('www.'):
                domain = domain[4:]
            return domain
        except Exception:
            return 'Unknown'


class NewsFilter:
    """Класс для фильтрации новостей"""
    
    def __init__(self):
        """Инициализация фильтра"""
        self.keywords_blacklist = [
            'реклама', 'advertisement', 'sponsored', 'промо',
            'акция', 'скидка', 'sale', 'discount'
        ]
    
    def filter_news(self, news_list: List[Dict[str, Any]], 
                   keywords: List[str] = None,
                   exclude_keywords: List[str] = None) -> List[Dict[str, Any]]:
        """Фильтрация новостей по ключевым словам"""
        filtered_news = []
        
        for news in news_list:
            title_lower = news['title'].lower()
            description_lower = news.get('description', '').lower()
            text = f"{title_lower} {description_lower}"
            
            # Исключаем рекламу
            if any(keyword in text for keyword in self.keywords_blacklist):
                continue
            
            # Исключаем по ключевым словам
            if exclude_keywords:
                if any(keyword.lower() in text for keyword in exclude_keywords):
                    continue
            
            # Включаем по ключевым словам
            if keywords:
                if any(keyword.lower() in text for keyword in keywords):
                    filtered_news.append(news)
            else:
                filtered_news.append(news)
        
        return filtered_news
    
    def remove_duplicates(self, news_list: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Удаление дубликатов новостей"""
        seen_titles = set()
        unique_news = []
        
        for news in news_list:
            title = news['title'].lower().strip()
            if title not in seen_titles:
                seen_titles.add(title)
                unique_news.append(news)
        
        return unique_news


class NewsFormatter:
    """Класс для форматирования новостей"""
    
    @staticmethod
    def format_news_list(news_list: List[Dict[str, Any]], 
                        max_items: int = 10) -> str:
        """Форматирование списка новостей для отправки"""
        if not news_list:
            return "📰 Новости не найдены."
        
        message = f"📰 Найдено новостей: {len(news_list)}\n\n"
        
        for i, news in enumerate(news_list[:max_items], 1):
            message += f"{i}. {news['title']}\n"
            
            if news.get('description'):
                description = news['description'][:100]
                if len(news['description']) > 100:
                    description += "..."
                message += f"   📝 {description}\n"
            
            message += f"   📅 {news['date']}\n"
            message += f"   📡 {news.get('source', 'Unknown')}\n"
            
            if news.get('url'):
                message += f"   🔗 {news['url']}\n"
            
            message += "\n"
        
        return message
    
    @staticmethod
    def format_digest(news_list: List[Dict[str, Any]], 
                     date: str = None) -> str:
        """Форматирование дайджеста"""
        if not date:
            date = datetime.now().strftime('%d.%m.%Y')
        
        message = f"📧 Ваш дайджест за {date}:\n\n"
        
        if not news_list:
            message += "📰 Новостей не найдено."
            return message
        
        # Группируем по источникам
        sources = {}
        for news in news_list:
            source = news.get('source', 'Unknown')
            if source not in sources:
                sources[source] = []
            sources[source].append(news)
        
        for source, source_news in sources.items():
            message += f"📡 {source}:\n"
            for news in source_news[:3]:  # Максимум 3 новости от источника
                message += f"• {news['title']}\n"
            message += "\n"
        
        message += "Используйте /top для просмотра полного списка новостей."
        
        return message
