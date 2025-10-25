# Инструкции по развертыванию News Aggregator Bot

## Быстрый старт

### 1. Подготовка окружения

```bash
# Перейдите в папку с ботом
cd lab1/bot

# Создайте виртуальное окружение (рекомендуется)
python -m venv venv

# Активируйте виртуальное окружение
# На Windows:
venv\Scripts\activate
# На macOS/Linux:
source venv/bin/activate

# Установите зависимости
pip install -r requirements.txt
```

### 2. Настройка бота

```bash
# Скопируйте файл конфигурации
cp env.example .env

# Отредактируйте .env файл
nano .env  # или любой другой редактор
```

Заполните файл `.env`:

```env
TELEGRAM_BOT_TOKEN=your_bot_token_here
NEWS_API_KEY=your_news_api_key_here
MEDIASTACK_API_KEY=your_mediastack_api_key_here
```

### 3. Получение токена бота

1. Найдите [@BotFather](https://t.me/botfather) в Telegram
2. Отправьте команду `/newbot`
3. Следуйте инструкциям:
   - Введите имя бота (например: "My News Bot")
   - Введите username бота (например: "my_news_bot")
4. Скопируйте полученный токен в файл `.env`

### 4. Запуск бота

```bash
# Запустите бота
python bot.py
```

Вы должны увидеть сообщение:
```
INFO - Запуск News Aggregator Bot...
INFO - Планировщик дайджестов запущен
```

## Дополнительная настройка

### API ключи для новостей (опционально)

#### News API
1. Зарегистрируйтесь на [newsapi.org](https://newsapi.org/)
2. Получите бесплатный API ключ
3. Добавьте его в файл `.env`

#### Mediastack API
1. Зарегистрируйтесь на [mediastack.com](https://mediastack.com/)
2. Получите бесплатный API ключ
3. Добавьте его в файл `.env`

### Настройка прокси (если необходимо)

Если вы находитесь в регионе с ограниченным доступом к Telegram API:

```env
PROXY_URL=http://proxy.example.com:8080
PROXY_USERNAME=username
PROXY_PASSWORD=password
```

## Тестирование

### Запуск тестов

```bash
# Запустите демонстрационные тесты
python test_examples.py
```

### Тестирование команд бота

1. Найдите вашего бота в Telegram по username
2. Отправьте команду `/start`
3. Попробуйте различные команды:
   - `/help` - список команд
   - `/top` - топ новостей
   - `/digest` - настройка дайджеста

## Развертывание на сервере

### Использование systemd (Linux)

1. Создайте файл сервиса:

```bash
sudo nano /etc/systemd/system/news-bot.service
```

2. Добавьте содержимое:

```ini
[Unit]
Description=News Aggregator Bot
After=network.target

[Service]
Type=simple
User=your_username
WorkingDirectory=/path/to/lab1/bot
ExecStart=/path/to/venv/bin/python bot.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

3. Активируйте сервис:

```bash
sudo systemctl daemon-reload
sudo systemctl enable news-bot
sudo systemctl start news-bot
```

### Использование Docker

1. Создайте `Dockerfile`:

```dockerfile
FROM python:3.9-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

CMD ["python", "bot.py"]
```

2. Создайте `docker-compose.yml`:

```yaml
version: '3.8'
services:
  news-bot:
    build: .
    environment:
      - TELEGRAM_BOT_TOKEN=${TELEGRAM_BOT_TOKEN}
      - NEWS_API_KEY=${NEWS_API_KEY}
    volumes:
      - ./bot_data.json:/app/bot_data.json
    restart: unless-stopped
```

3. Запустите:

```bash
docker-compose up -d
```

## Мониторинг и логи

### Просмотр логов

```bash
# Если используете systemd
sudo journalctl -u news-bot -f

# Если запускаете напрямую
tail -f bot.log
```

### Мониторинг состояния

```bash
# Проверка статуса сервиса
sudo systemctl status news-bot

# Проверка процессов
ps aux | grep bot.py
```

## Обновление бота

1. Остановите бота:
```bash
sudo systemctl stop news-bot
```

2. Обновите код:
```bash
git pull origin main
```

3. Перезапустите бота:
```bash
sudo systemctl start news-bot
```

## Устранение неполадок

### Частые проблемы

1. **Ошибка "TELEGRAM_BOT_TOKEN не найден"**
   - Проверьте файл `.env`
   - Убедитесь, что токен скопирован правильно

2. **Бот не отвечает**
   - Проверьте интернет-соединение
   - Убедитесь, что бот запущен
   - Проверьте логи на ошибки

3. **Ошибки получения новостей**
   - Проверьте API ключи
   - Убедитесь, что источники доступны
   - Проверьте настройки прокси

### Логи и отладка

```bash
# Включите подробное логирование
export LOG_LEVEL=DEBUG
python bot.py
```

## Безопасность

### Рекомендации

1. **Никогда не коммитьте файл `.env`**
2. **Используйте виртуальное окружение**
3. **Ограничьте права доступа к файлам**
4. **Регулярно обновляйте зависимости**

### Ограничение доступа

```bash
# Ограничьте доступ к конфигурационным файлам
chmod 600 .env
chmod 600 bot_data.json
```

## Масштабирование

### Для большого количества пользователей

1. **Используйте базу данных вместо JSON**
2. **Добавьте кэширование**
3. **Используйте очереди для обработки**
4. **Добавьте балансировку нагрузки**

### Пример с PostgreSQL

```python
# Замените JSON на PostgreSQL
import psycopg2

def save_user_data(self, user_id, data):
    conn = psycopg2.connect(DATABASE_URL)
    # ... код для работы с БД
```

## Поддержка

Если у вас возникли проблемы:

1. Проверьте логи бота
2. Убедитесь в правильности конфигурации
3. Проверьте доступность внешних сервисов
4. Обратитесь к документации библиотек

---

**Автор:** Daniil Korinenko  
**Университет:** МАГА, 3 семестр  
**Курс:** Основы web-разработки
