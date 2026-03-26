# Izotop Connect Bot Deployment On Linux

Дата: 2026-03-26

Этот гайд рассчитан на твой текущий сценарий:

- панель `Remnawave` уже живёт на `panel.izotop-connect.online`
- бота поднимаем на том же польском сервере
- отдельный поддомен `bot.` не используем
- webhook Tribute будет приходить на:
  - `https://panel.izotop-connect.online/webhooks/tribute`

## Что происходит

У тебя теперь два приложения на одном сервере:

1. `Remnawave Panel`
   - живёт за `Caddy`
   - отвечает за обычный UI панели

2. `Izotop Connect Bot`
   - это Python-приложение
   - внутри него:
     - Telegram bot polling
     - FastAPI endpoint для webhook Tribute

Публично наружу боту нужен только один маршрут:

- `/webhooks/tribute`

Опционально:

- `/healthz`

## Почему `panel.` можно оставить

Можно не делать `bot.izotop-connect.online`, если тебе так удобнее.

Тогда `Caddy` на `panel.izotop-connect.online` должен делать роутинг по путям:

- `/webhooks/tribute` -> Python app
- `/healthz` -> Python app
- всё остальное -> `Remnawave Panel`

## Что такое `pyproject.toml`

Это обычный файл конфигурации Python-проекта.

Он заменяет старые комбинации вроде:

- `requirements.txt`
- `setup.py`
- куски конфигов линтера/сборки

Что лежит у нас внутри:

- имя проекта
- версия
- список зависимостей
- требуемая версия Python

Для тебя практически это значит только одно:

- установка делается через:

```bash
pip install -e .
```

А `pip` сам читает зависимости из `pyproject.toml`.

## Подготовка директории на сервере

На польском VPS:

```bash
mkdir -p /opt/izotop-connect-bot
cd /opt/izotop-connect-bot
```

Скопируй туда проект.

Если ты загружаешь вручную, то в итоге в `/opt/izotop-connect-bot` должны лежать:

- `pyproject.toml`
- `.env`
- `src/`
- `docs/`

## Установка Python 3.12

Если на сервере уже есть `python3.12`, просто используй его.

Если нет:

```bash
apt update
apt install -y python3.12 python3.12-venv
```

## Создание окружения и установка зависимостей

```bash
cd /opt/izotop-connect-bot
python3.12 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e .
```

## .env для бота

Минимально тебе нужно:

```env
APP_HOST=127.0.0.1
APP_PORT=8080
APP_BASE_URL=http://127.0.0.1:8080

BOT_TOKEN=...
BOT_PUBLIC_NAME=Izotop Connect
BOT_SUPPORT_URL=https://t.me/+....
BOT_BUY_URL=https://...
BOT_ADMIN_IDS=123456789

TRIBUTE_WEBHOOK_SECRET=...
TRIBUTE_SIGNATURE_HEADER=trbt-signature

REMNAWAVE_BASE_URL=https://panel.izotop-connect.online
REMNAWAVE_TOKEN=...
REMNAWAVE_INTERNAL_SQUAD_UUID=...
REMNAWAVE_EXTERNAL_SQUAD_UUID=
REMNAWAVE_USER_PREFIX=tg
REMNAWAVE_SSL_IGNORE=false

DATABASE_URL=sqlite+aiosqlite:///./data/izotop_connect.db
```

### Почему `APP_HOST=127.0.0.1`

Потому что наружу бот открывать напрямую не надо.

До него должен ходить только `Caddy` на этой же машине.

## Caddy

Если ты уже держишь панель на `panel.izotop-connect.online`, логика должна быть такая:

- webhook Tribute идёт в бот
- весь остальной трафик идёт в панель

Пример `Caddyfile`:

```caddy
panel.izotop-connect.online {
    @bot_paths {
        path /webhooks/tribute /healthz
    }

    handle @bot_paths {
        reverse_proxy 127.0.0.1:8080
    }

    handle {
        reverse_proxy remnawave:3000
    }
}

sub.izotop-connect.online {
    reverse_proxy remnawave:3000
}
```

Важно:

- блок с `@bot_paths` должен быть выше общего `handle`
- иначе webhook улетит в панель, а не в Python app

После правки:

```bash
cd /opt/remnawave/caddy
docker compose restart caddy
docker compose logs -f -t
```

## systemd service

Готовый unit-файл лежит тут:

- `/Users/izotop/izotop vpn/deploy/systemd/izotop-connect-bot.service`

На сервере его надо положить так:

```bash
cp /opt/izotop-connect-bot/deploy/systemd/izotop-connect-bot.service /etc/systemd/system/izotop-connect-bot.service
```

Если проект на сервер загружен в `/opt/izotop-connect-bot`, то unit уже подходит без изменений.

### Что делает unit

- запускает бота из `.venv`
- читает переменные из `.env`
- автоматически перезапускает процесс при падении

## Запуск через systemd

```bash
systemctl daemon-reload
systemctl enable izotop-connect-bot
systemctl start izotop-connect-bot
systemctl status izotop-connect-bot
```

Логи:

```bash
journalctl -u izotop-connect-bot -f
```

## Что ставить в Tribute webhook URL

Раз ты хочешь оставить `panel.`, ставь:

```text
https://panel.izotop-connect.online/webhooks/tribute
```

## Порядок действий

1. Залить проект в `/opt/izotop-connect-bot`
2. Создать `.venv`
3. Установить зависимости
4. Заполнить `.env`
5. Добавить path-routing в `Caddy`
6. Поставить `systemd` service
7. Запустить сервис
8. Проверить:
   - `https://panel.izotop-connect.online/healthz`
   - `systemctl status izotop-connect-bot`
   - `journalctl -u izotop-connect-bot -f`
9. Вставить в Tribute:
   - `https://panel.izotop-connect.online/webhooks/tribute`
10. Нажать `Отправить тестовый запрос`

## Что делать, если webhook не проходит

### 401

Почти всегда:

- неверный `TRIBUTE_WEBHOOK_SECRET`

### 404

Почти всегда:

- Caddy не прокидывает `/webhooks/tribute` в бота

### 502

Почти всегда:

- бот не запущен
- или слушает не `127.0.0.1:8080`

## Что делать, если хочешь проверить локально без Tribute

На сервере:

```bash
curl http://127.0.0.1:8080/healthz
```

Должно вернуть:

```json
{"status":"ok"}
```

## Связанные файлы

- План бота: `/Users/izotop/izotop vpn/docs/telegram-bot-plan.md`
- Linux service: `/Users/izotop/izotop vpn/deploy/systemd/izotop-connect-bot.service`
