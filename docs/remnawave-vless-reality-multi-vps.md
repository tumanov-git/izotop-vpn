# Remnawave + VLESS + REALITY на нескольких VPS

Дата: 2026-03-21

Этот гайд переписывает схему под масштабирование. Исходим из того, что у тебя будет:

- один `management VPS` для панели и автоматики;
- несколько `edge VPS` для VPN-трафика;
- `VLESS + REALITY` на каждой edge-ноде;
- Telegram-бот и Tribute webhook handler живут рядом с панелью.

## Короткий вывод

Если ты заранее планируешь несколько VPS, правильная схема такая:

- `Remnawave Panel` не ставить на первый VPN-сервер;
- вынести панель на отдельный management VPS;
- на VPN-серверах держать только `Remnawave Node`;
- каждый новый VPS добавлять как отдельную ноду и отдельный Host в панели.

Это проще в эксплуатации и не создаёт конфликтов вокруг `443`.

## Архитектура

```text
                           +---------------------------+
                           |      management VPS       |
                           |---------------------------|
internet ----------------->| panel.example.com:443     |
                           | Remnawave Panel           |
                           | PostgreSQL панели         |
                           | Telegram bot              |
                           | Tribute webhooks          |
                           +------------+--------------+
                                        |
                                        | Node API / control plane
                                        |
                +-----------------------+------------------------+
                |                       |                        |
                v                       v                        v
      +------------------+   +------------------+   +------------------+
      |   edge VPS NL    |   |   edge VPS DE    |   |   edge VPS FI    |
      |------------------|   |------------------|   |------------------|
      | nl-001.example.com|  | de-001.example.com|  | fi-001.example.com|
      | Remnawave Node   |   | Remnawave Node   |   | Remnawave Node   |
      | Xray + REALITY   |   | Xray + REALITY   |   | Xray + REALITY   |
      | client port 443  |   | client port 443  |   | client port 443  |
      +------------------+   +------------------+   +------------------+
```

## Почему это лучше, чем panel + node на одном VPS

- `REALITY` можно спокойно держать на `443` на edge-серверах;
- панель не конфликтует с VPN-портами;
- новый VPS добавляется без переноса панели;
- бот и вебхуки Tribute живут в одном месте;
- проще делать бэкапы и мониторинг;
- если одна edge-нода падает, панель и бот продолжают работать.

## Роли серверов

### Management VPS

На этом сервере размещаются:

- `Remnawave Panel`
- PostgreSQL панели
- reverse proxy (`Caddy` или `Traefik`)
- Telegram-бот
- webhook endpoint для Tribute

На этом сервере не нужен клиентский VPN-inbound.

### Edge VPS

На каждом таком сервере размещаются:

- `Remnawave Node`
- `Xray-core`
- `VLESS + REALITY` inbound

На edge VPS не нужна панель.

## Рекомендуемая адресация и домены

Минимально:

- `panel.example.com` -> management VPS
- `nl-001.example.com` -> Netherlands edge VPS
- `de-001.example.com` -> Germany edge VPS
- `fi-001.example.com` -> Finland edge VPS

Нейминг лучше держать строгим сразу:

- node code: `NL-001`, `DE-001`, `FI-001`
- host name: `Netherlands 1`, `Germany 1`, `Finland 1`
- fqdn: `nl-001.example.com`, `de-001.example.com`, `fi-001.example.com`

## Что открывать по портам

### Management VPS

Открыть наружу:

- `80/tcp`
- `443/tcp`

Опционально:

- `22/tcp` только с твоего IP

Не открывать наружу:

- внутренние порты контейнеров панели
- PostgreSQL

### Edge VPS

Открыть наружу:

- `443/tcp` для `VLESS + REALITY`

Опционально:

- `22/tcp` только с твоего IP

Отдельно:

- `Node API port` открыть только для management VPS

Пример:

- NL node API: `2222/tcp`
- DE node API: `2222/tcp`
- FI node API: `2222/tcp`

Но доступ к этому порту разрешён только с IP management-сервера.

## Шаг 1. Подними management VPS

Сервер:

- Ubuntu 22.04/24.04 или Debian 12
- 2-4 vCPU
- 4 GB RAM минимум

Установи базовые пакеты:

```bash
apt update
apt upgrade -y
apt install -y curl ca-certificates gnupg ufw jq openssl
curl -fsSL https://get.docker.com | sh
```

Открой firewall:

```bash
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw enable
```

## Шаг 2. Поставь Remnawave Panel на management VPS

```bash
mkdir -p /opt/remnawave
cd /opt/remnawave
curl -o docker-compose.yml https://raw.githubusercontent.com/remnawave/backend/refs/heads/main/docker-compose-prod.yml
curl -o .env https://raw.githubusercontent.com/remnawave/backend/refs/heads/main/.env.sample
```

Сгенерируй секреты:

```bash
cd /opt/remnawave
sed -i "s/^JWT_AUTH_SECRET=.*/JWT_AUTH_SECRET=$(openssl rand -hex 64)/" .env
sed -i "s/^JWT_API_TOKENS_SECRET=.*/JWT_API_TOKENS_SECRET=$(openssl rand -hex 64)/" .env
sed -i "s/^METRICS_PASS=.*/METRICS_PASS=$(openssl rand -hex 64)/" .env
sed -i "s/^WEBHOOK_SECRET_HEADER=.*/WEBHOOK_SECRET_HEADER=$(openssl rand -hex 64)/" .env
pw=$(openssl rand -hex 24) && sed -i "s/^POSTGRES_PASSWORD=.*/POSTGRES_PASSWORD=$pw/" .env && sed -i "s|^\(DATABASE_URL=\"postgresql://postgres:\)[^\@]*\(@.*\)|\1$pw\2|" .env
```

Проверь руками `.env`:

```env
FRONT_END_DOMAIN=panel.example.com
SUB_PUBLIC_DOMAIN=sub.example.com
```

Если отдельную subscription page пока не поднимаешь, можешь временно использовать домен панели, но под масштабирование лучше сразу держать отдельный поддомен:

- `panel.example.com` для админки
- `sub.example.com` для публичных подписок

Запуск:

```bash
cd /opt/remnawave
docker compose up -d
docker compose logs -f -t
```

## Шаг 3. Поставь reverse proxy на management VPS

Самый простой вариант: `Caddy`.

`/opt/remnawave/caddy/Caddyfile`:

```caddy
https://panel.example.com {
    reverse_proxy * http://remnawave:3000
}
```

`/opt/remnawave/caddy/docker-compose.yml`:

```yaml
services:
  caddy:
    image: caddy:2.9
    container_name: caddy
    hostname: caddy
    restart: always
    ports:
      - "0.0.0.0:443:443"
      - "0.0.0.0:80:80"
    networks:
      - remnawave-network
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile
      - caddy-ssl-data:/data

networks:
  remnawave-network:
    name: remnawave-network
    driver: bridge
    external: true

volumes:
  caddy-ssl-data:
    driver: local
    external: false
    name: caddy-ssl-data
```

Запуск:

```bash
cd /opt/remnawave/caddy
docker compose up -d
docker compose logs -f -t
```

После этого:

- открой `https://panel.example.com`
- зарегистрируй первого `super-admin`
- в `Remnawave Settings` выпусти `API Token` для бота

## Шаг 4. Подготовь каждый edge VPS

На каждой VPN-ноде:

```bash
apt update
apt upgrade -y
apt install -y curl ca-certificates gnupg ufw jq openssl
curl -fsSL https://get.docker.com | sh
```

### Firewall для edge VPS

Пример для ноды NL:

```bash
ufw allow OpenSSH
ufw allow 443/tcp
ufw allow from <MANAGEMENT_VPS_IP> to any port 2222 proto tcp
ufw enable
```

То же самое повторяешь для каждой ноды.

Важно:

- `443/tcp` открыт для клиентов;
- `2222/tcp` открыт только с management VPS;
- ничего лишнего наружу не торчит.

## Шаг 5. Создай ноды в панели

В панели:

1. `Nodes -> Management`
2. `Create new node`

Пример для `NL-001`:

- `Country`: Netherlands
- `Internal name`: `NL-001`
- `Address`: `nl-001.example.com`
- `Port`: `2222`

После создания панель даст `docker-compose.yml` для ноды.

Повтори для:

- `DE-001`
- `FI-001`

## Шаг 6. Поставь Remnawave Node на каждый edge VPS

На сервере `NL`:

```bash
mkdir -p /opt/remnanode
cd /opt/remnanode
```

Вставь `docker-compose.yml`, который сгенерировала панель для `NL-001`.

Потом:

```bash
cd /opt/remnanode
docker compose up -d
docker compose logs -f -t
```

Сделай то же самое на `DE` и `FI`.

После запуска убедись в панели, что ноды стали `online`.

## Шаг 7. Сгенерируй REALITY-ключи для каждой ноды

На каждом edge VPS:

```bash
docker exec -it remnanode xray x25519
openssl rand -hex 8
```

Для каждой ноды сохраняешь отдельно:

- `privateKey`
- `publicKey`
- `shortId`

Ключи не надо шарить между серверами. Для каждой ноды лучше своя пара.

## Шаг 8. Подготовь базовый профиль VLESS + REALITY

Есть два рабочих подхода.

### Вариант A. Один профиль на каждую ноду

Самый простой и прозрачный вариант:

- `VLESS-REALITY-NL`
- `VLESS-REALITY-DE`
- `VLESS-REALITY-FI`

Внутри отличаются:

- `privateKey`
- `shortIds`
- `serverNames`
- иногда `target`

### Вариант B. Единый шаблон и разные host bindings

Подходит позже, когда уже будет больше автоматизации. На старте я рекомендую вариант A.

## Пример профиля для одной ноды

Ниже профиль для `NL-001`:

```json
{
  "log": {
    "loglevel": "warning"
  },
  "dns": {},
  "inbounds": [
    {
      "tag": "VLESS_TCP_REALITY",
      "port": 443,
      "listen": "0.0.0.0",
      "protocol": "vless",
      "settings": {
        "clients": [],
        "decryption": "none"
      },
      "streamSettings": {
        "network": "raw",
        "security": "reality",
        "realitySettings": {
          "show": false,
          "target": "www.microsoft.com:443",
          "serverNames": [
            "www.microsoft.com"
          ],
          "privateKey": "REPLACE_NL_PRIVATE_KEY",
          "shortIds": [
            "REPLACE_NL_SHORT_ID"
          ]
        }
      },
      "sniffing": {
        "enabled": true,
        "destOverride": [
          "http",
          "tls",
          "quic"
        ]
      }
    }
  ],
  "outbounds": [
    {
      "tag": "DIRECT",
      "protocol": "freedom"
    },
    {
      "tag": "BLOCK",
      "protocol": "blackhole"
    }
  ],
  "routing": {
    "rules": []
  }
}
```

Повтори тот же профиль для `DE` и `FI`, заменив ключи и при необходимости `serverNames`.

## Шаг 9. Назначь профили нодам

В `Nodes -> Management`:

- `NL-001` -> профиль `VLESS-REALITY-NL`
- `DE-001` -> профиль `VLESS-REALITY-DE`
- `FI-001` -> профиль `VLESS-REALITY-FI`

## Шаг 10. Создай Hosts

В `Hosts` создай по одному host на каждую страну.

### Host: Netherlands 1

- `Name`: `Netherlands 1`
- `Address`: `nl-001.example.com`
- `Port`: `443`
- inbound: `VLESS_TCP_REALITY`
- node binding: `NL-001`

### Host: Germany 1

- `Name`: `Germany 1`
- `Address`: `de-001.example.com`
- `Port`: `443`
- inbound: `VLESS_TCP_REALITY`
- node binding: `DE-001`

### Host: Finland 1

- `Name`: `Finland 1`
- `Address`: `fi-001.example.com`
- `Port`: `443`
- inbound: `VLESS_TCP_REALITY`
- node binding: `FI-001`

## Шаг 11. Сразу продумай squads

Под масштабирование это важно с первого дня.

### Базовый вариант

Оставь:

- `Default-Squad` для обычных пользователей

И включи в него:

- `VLESS_TCP_REALITY`

### Если хочешь тарифы

Сразу сделай разные squads:

- `basic`
- `premium`
- `vip`

И потом управляй не пользователями по одному, а доступом через squads:

- `basic`: NL
- `premium`: NL + DE + FI
- `vip`: все страны + будущие скрытые hosts

Это гораздо лучше ложится на бота и биллинг.

## Шаг 12. Как выдавать пользователю несколько стран

Логика такая:

1. у пользователя один аккаунт в Remnawave;
2. подписка клиента содержит список доступных hosts;
3. какие hosts увидит пользователь, определяется через squad и шаблоны подписки.

То есть тебе не надо создавать отдельный ключ под каждую страну. Один пользователь получает одну подписку, а внутри неё несколько точек входа.

## Рекомендованная структура тарифов

Под VPN-сервис я бы сразу делал не по серверам, а по доступным наборам.

### Тариф Start

- 1 устройство или базовый лимит
- только `NL`

### Тариф Plus

- несколько устройств
- `NL + DE + FI`

### Тариф Pro

- все доступные ноды
- приоритетные новые страны

В Tribute и в боте потом проще оперировать именно тарифом, а не вручную списком серверов.

## Как добавляется новый VPS потом

Пример: появился новый сервер в Польше.

Порядок:

1. Создаёшь DNS `pl-001.example.com`
2. Поднимаешь новый edge VPS
3. Ставишь Docker
4. Настраиваешь firewall:
   - `443/tcp` наружу
   - `2222/tcp` только от management VPS
5. В панели создаёшь node `PL-001`
6. Забираешь сгенерированный `docker-compose.yml`
7. Ставишь `Remnawave Node`
8. Генерируешь REALITY-ключи
9. Создаёшь профиль `VLESS-REALITY-PL`
10. Создаёшь host `Poland 1`
11. Добавляешь host в нужные тарифы / squads

Панель, бот и Tribute при этом не переезжают и почти не меняются.

## Как это связано с Telegram-ботом

Бот должен работать только с management VPS.

Ему нужны:

- `Remnawave API Token`
- локальная БД со статусом подписки
- webhook endpoint Tribute

Бот не должен ходить на edge VPS напрямую.

Его логика:

1. Tribute прислал `new_subscription` или `renewed_subscription`
2. локальная БД обновила `expires_at`, тариф и статус
3. бот создал или обновил пользователя в Remnawave
4. пользователю отдаётся `subscription URL`

Если потом тариф меняется, бот просто меняет squad или правила доступа, а не пересоздаёт всю схему.

## Что хранить в локальной БД бота

Минимум:

- `telegram_user_id`
- `telegram_username`
- `tribute_channel_id`
- `tribute_subscription_id`
- `current_plan`
- `expires_at`
- `remnawave_user_id`
- `remnawave_subscription_url`
- `status`

Этого достаточно, чтобы управлять доступом на несколько стран и несколько VPS.

## Что делать с уже существующими 20 подписчиками

Твоя ручная инициализация здесь полностью нормальна:

1. руками вносишь их в локальную БД;
2. руками ставишь текущий `expires_at`;
3. если нужно, создаёшь им пользователей в Remnawave;
4. дальше всё уже поддерживается вебхуками Tribute.

## Production-рекомендации

### 1. Панель не смешивать с traffic edge

Даже если технически можешь, под рост это плохая схема.

### 2. Делать один сервер = одна страна = одна нода

Так проще:

- дебажить;
- отключать проблемный сервер;
- считать стоимость;
- продавать тарифы по странам.

### 3. Хранить ключи REALITY отдельно по нодам

Не переиспользовать одни и те же ключи на нескольких VPS.

### 4. Сразу думать тарифами, а не пользователями

Управление через squads масштабируется лучше, чем ручная логика на каждого человека.

### 5. Бэкапить management VPS

Критично сохранить:

- БД панели
- `.env` панели
- API token бота
- локальную БД бота

## Самый практичный стартовый rollout

### Этап 1

- 1 management VPS
- 1 edge VPS (`NL`)
- бот в `SQLite`
- Tribute webhooks

### Этап 2

- добавить `DE`
- добавить `FI`
- разделить тарифы на `basic` и `premium`

### Этап 3

- добавить мониторинг
- автоматическое отключение просроченных доступов
- ротацию проблемных нод

## Источники

- Remnawave Quick Start: https://docs.rw/docs/overview/quick-start/
- Remnawave Panel install: https://docs.rw/docs/install/remnawave-panel/
- Remnawave Node install: https://docs.rw/docs/install/remnawave-node/
- Remnawave Hosts: https://docs.rw/docs/learn-en/hosts
- Remnawave Nodes: https://docs.rw/docs/learn-en/nodes/
- Remnawave Squads: https://docs.rw/docs/learn-en/squads/
- Remnawave Xray JSON Advanced: https://docs.rw/docs/learn/xray-json-advanced/
- Remnawave Server-Side Routing: https://docs.rw/docs/learn-en/server-routing/
- Xray REALITY transport: https://xtls.github.io/en/config/transport.html

## Связанные документы

- Single VPS вариант: `/Users/izotop/izotop vpn/docs/remnawave-vless-reality-install.md`
