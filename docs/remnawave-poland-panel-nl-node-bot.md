# Remnawave: панель в Польше, нода в Нидерландах, Telegram-бот

Дата: 2026-03-21

Этот документ написан под твою реальную схему без абстракций:

- отдельный `management VPS` в Польше;
- на нём будет `Remnawave Panel`;
- старая рабочая VPN-машина в Нидерландах остаётся;
- на NL-сервере уже крутится `Amnezia`;
- `Remnawave Node` ставим на этот NL-сервер рядом с Amnezia;
- из-за занятого `443/tcp` поднимаем `VLESS + REALITY` для Remnawave на `8443/tcp`;
- внутренний порт `Node API` используем `2222/tcp`;
- потом к панели прикручиваем Telegram-бота и Tribute webhooks.

## Итоговая схема

```text
management VPS (Poland)
  panel.example.com:443
    -> Caddy
    -> Remnawave Panel
    -> PostgreSQL
    -> Redis
    -> Telegram bot
    -> Tribute webhook handler

old NL VPS
  443/tcp      -> уже занят amnezia-xray
  46005/udp    -> уже занят amnezia-awg
  8443/tcp     -> новый VLESS + REALITY для Remnawave Node
  2222/tcp     -> внутренний Node API, доступен только с IP польского VPS
```

## Что уже известно по NL-серверу

По твоему выводу:

- `443/tcp` занят контейнером `amnezia-xray`;
- `46005/udp` занят контейнером `amnezia-awg`;
- `ufw` выключен;
- правила Docker/iptables уже есть;
- значит `443` трогать нельзя;
- новый inbound для Remnawave надо ставить на другой порт.

Поэтому в этом гайде всё зафиксировано так:

- `panel.example.com` -> Польша;
- `nl-001.example.com` -> старый NL VPS;
- `REALITY` на `8443`;
- `Node API` на `2222`.

## Часть 1. Что подготовить заранее

Тебе понадобятся:

- домен или поддомен для панели, например `panel.example.com`;
- домен или поддомен для ноды, например `nl-001.example.com`;
- IP польского сервера;
- IP нидерландского сервера;
- root-доступ по SSH на оба сервера.

### DNS

Создай записи:

- `panel.example.com` -> IP польского VPS
- `nl-001.example.com` -> IP NL VPS

Если используешь Cloudflare:

- для панели проксирование можно оставить по ситуации;
- для `nl-001.example.com` лучше `DNS only`, без proxy.

## Часть 2. Установка панели на польский VPS

Ниже весь процесс без пропусков.

### 2.1. Подключись к польскому VPS

```bash
ssh root@IP_ПОЛЬСКОГО_VPS
```

### 2.2. Обнови систему

```bash
apt update
apt upgrade -y
timedatectl set-timezone Europe/Warsaw
```

### 2.3. Установи базовые пакеты

```bash
apt install -y curl ca-certificates gnupg ufw jq openssl
```

### 2.4. Установи Docker

```bash
curl -fsSL https://get.docker.com | sh
```

Проверь:

```bash
docker --version
docker compose version
```

### 2.5. Настрой firewall на польском VPS

```bash
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw enable
ufw status
```

Для панели этого достаточно.

### 2.6. Скачай Remnawave Panel

```bash
mkdir -p /opt/remnawave
cd /opt/remnawave
curl -o docker-compose.yml https://raw.githubusercontent.com/remnawave/backend/refs/heads/main/docker-compose-prod.yml
curl -o .env https://raw.githubusercontent.com/remnawave/backend/refs/heads/main/.env.sample
```

### 2.7. Сгенерируй секреты

```bash
cd /opt/remnawave
sed -i "s/^JWT_AUTH_SECRET=.*/JWT_AUTH_SECRET=$(openssl rand -hex 64)/" .env
sed -i "s/^JWT_API_TOKENS_SECRET=.*/JWT_API_TOKENS_SECRET=$(openssl rand -hex 64)/" .env
sed -i "s/^METRICS_PASS=.*/METRICS_PASS=$(openssl rand -hex 64)/" .env
sed -i "s/^WEBHOOK_SECRET_HEADER=.*/WEBHOOK_SECRET_HEADER=$(openssl rand -hex 64)/" .env
pw=$(openssl rand -hex 24) && sed -i "s/^POSTGRES_PASSWORD=.*/POSTGRES_PASSWORD=$pw/" .env && sed -i "s|^\(DATABASE_URL=\"postgresql://postgres:\)[^\@]*\(@.*\)|\1$pw\2|" .env
```

### 2.8. Проверь `.env`

Открой файл:

```bash
cd /opt/remnawave
nano .env
```

Проверь и выставь минимум следующее:

```env
APP_PORT=3000
API_INSTANCES=1
FRONT_END_DOMAIN=panel.example.com
SUB_PUBLIC_DOMAIN=panel.example.com/api/sub
```

Что здесь важно:

- `APP_PORT=3000` оставляем как есть;
- `API_INSTANCES=1` для твоего management VPS нормально;
- `FRONT_END_DOMAIN` должен быть доменом панели;
- `SUB_PUBLIC_DOMAIN` на старте можно оставить на домене панели.

Если потом захочешь красивую отдельную страницу подписок, вынесешь это на отдельный поддомен.

### 2.9. Запусти панель

```bash
cd /opt/remnawave
docker compose up -d
docker compose logs -f -t
```

На этом этапе сами контейнеры панели уже должны подняться.

### 2.10. Поставь reverse proxy

Создай каталог:

```bash
mkdir -p /opt/remnawave/caddy
cd /opt/remnawave/caddy
```

Создай `Caddyfile`:

```bash
nano /opt/remnawave/caddy/Caddyfile
```

Содержимое:

```caddy
https://panel.example.com {
    reverse_proxy * http://remnawave:3000
}

:443 {
    tls internal
    respond 204
}
```

Создай `docker-compose.yml`:

```bash
nano /opt/remnawave/caddy/docker-compose.yml
```

Содержимое:

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

Запусти:

```bash
cd /opt/remnawave/caddy
docker compose up -d
docker compose logs -f -t
```

### 2.11. Зайди в панель

Открой:

```text
https://izotop-connect-
```

Сделай:

1. зарегистрируй первого пользователя;
2. этот пользователь станет `super-admin`;
3. зайди в `Remnawave Settings`;
4. создай `API Token` для будущего бота.

Сразу сохрани:

- URL панели
- логин
- API token

## Часть 3. Подготовка NL-сервера под Remnawave Node

Это старый сервер, где уже есть Amnezia.

Наша задача:

- ничего не ломаем;
- `443` не трогаем;
- новый сервис сажаем на `8443`;
- Node API даём `2222`.

### 3.1. Подключись к NL-серверу

```bash
ssh root@IP_NL_VPS
```

### 3.2. Обнови пакеты

```bash
apt update
apt upgrade -y
apt install -y curl ca-certificates gnupg jq openssl
```

Если Docker уже есть, повторно ставить не надо. Если нет:

```bash
curl -fsSL https://get.docker.com | sh
```

### 3.3. Проверь, что старые сервисы живы

```bash
docker ps
ss -tulpn
```

Ожидаемо увидишь:

- `amnezia-xray` на `443/tcp`
- `amnezia-awg` на `46005/udp`

Если это так, идём дальше.

## Часть 4. Создание ноды в панели

Теперь возвращаемся в польскую панель.

### 4.1. Создай новую ноду

В панели:

1. `Nodes -> Management`
2. `Create new node`

Заполни:

- `Country`: Netherlands
- `Internal name`: `NL-001`
- `Address`: `nl-001.example.com`
- `Port`: `2222`

Важно:

- этот `Port` не для VPN-клиентов;
- это внутренний `Node API` порт, по которому панель говорит с Node.

### 4.2. Скопируй `docker-compose.yml`

После создания Remnawave покажет кнопку:

- `Copy docker-compose.yml`

Скопируй этот файл. Он понадобится на NL-сервере.

Пока окно не закрывай, если боишься потерять конфиг.

## Часть 5. Установка Remnawave Node на NL-сервер

### 5.1. Создай каталог

На NL-сервере:

```bash
mkdir -p /opt/remnanode
cd /opt/remnanode
```

### 5.2. Создай `docker-compose.yml`

```bash
nano /opt/remnanode/docker-compose.yml
```

Вставь содержимое, которое дала панель.

### 5.3. Проверь `docker-compose.yml`

Там должны быть переменные примерно такого вида:

```yaml
environment:
  - NODE_PORT=2222
  - SECRET_KEY=...
```

Если `NODE_PORT` не `2222`, поправь его на `2222`.

### 5.4. Запусти Node

```bash
cd /opt/remnanode
docker compose up -d
docker compose logs -f -t
```

### 5.5. Проверь, что нода слушает `2222`

```bash
ss -tulpn | grep 2222
```

## Часть 6. Закрыть `2222` от всего интернета

Это очень важно.

У тебя `ufw` на NL-сервере выключен, поэтому есть два варианта:

- включить `ufw`;
- или ограничить доступ через firewall у провайдера.

Если выбираешь `ufw`, сначала не делай это вслепую. Сначала разреши SSH и нужные порты.

### 6.1. Безопасный вариант через `ufw`

На NL-сервере:

```bash
apt install -y ufw
ufw allow OpenSSH
ufw allow 443/tcp
ufw allow 46005/udp
ufw allow 8443/tcp
ufw allow from 85.155.230.85 to any port 2222 proto tcp
ufw enable
ufw status
```

Смысл:

- `443/tcp` нужен старой Amnezia;
- `46005/udp` нужен старой Amnezia;
- `8443/tcp` нужен новой ноде Remnawave;
- `2222/tcp` разрешён только польскому management VPS.

Если не хочешь трогать `ufw`, сделай то же ограничение в панели управления хостера.

## Часть 7. Генерация REALITY-ключей на NL-сервере

### 7.1. Сгенерируй ключевую пару

На NL-сервере:

```bash
docker exec -it remnanode xray x25519
```

Сохрани:

- `Private key`
- `Public key`

### 7.2. Сгенерируй `shortId`

```bash
openssl rand -hex 8
```

Сохрани результат. Это будет `shortId`.

## Часть 8. Создай профиль VLESS + REALITY в панели

Теперь снова идёшь в польскую панель.

### 8.1. Создай Config Profile

1. `Config Profiles`
2. `Create Config Profile`
3. Назови профиль: `VLESS-REALITY-NL-8443`

### 8.2. Вставь профиль

Используй этот профиль как базу:

```json
{
  "log": {
    "loglevel": "warning"
  },
  "dns": {},
  "inbounds": [
    {
      "tag": "VLESS_TCP_REALITY",
      "port": 8443,
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
          "privateKey": "PASTE_REALITY_PRIVATE_KEY",
          "shortIds": [
            "PASTE_SHORT_ID"
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

### 8.3. Что заменить

Обязательно замени:

- `privateKey` -> на твой `Private key`
- `shortIds` -> на твой `shortId`

Оставь:

- `port: 8443`
- `tag: VLESS_TCP_REALITY`

## Часть 9. Назначь профиль ноде

В панели:

1. `Nodes -> Management`
2. открой `NL-001`
3. `Change Profile`
4. выбери `VLESS-REALITY-NL-8443`
5. включи inbound `VLESS_TCP_REALITY`
6. сохрани

## Часть 10. Создай Host

В панели:

1. `Hosts`
2. `Create new host`

Заполни:

- `Host visibility`: enabled
- `Remark`: `Netherlands`
- `Inbound`: `VLESS_TCP_REALITY`
- `Address`: `nl-001.example.com`

Порт обычно подтянется из inbound автоматически. Если нет, поставь:

- `Port`: `8443`

Сохрани.

## Часть 11. Проверь Internal Squad

Очень частая ошибка: всё создано, а пользователь ничего не видит.

Проверь:

1. `Internal Squads`
2. открой `Default-Squad`
3. включи inbound `VLESS_TCP_REALITY`
4. сохрани

Если этого не сделать, у пользователя не будет доступа к host, даже если нода и профиль уже существуют.

## Часть 12. Создай тестового пользователя

В панели:

1. `Users`
2. `Create user`

Заполни:

- `Username`: `test_nl_001`
- `Subscription expires at`: например через 30 дней
- `Internal Squad`: `Default-Squad`
- трафик можно оставить без жёстких ограничений на тест

После создания:

- скопируй `Subscription URL`
- открой ссылку в браузере
- убедись, что там есть хост `Netherlands`

## Часть 13. Подключи клиент и проверь VPN

Импортируй `Subscription URL` в клиент:

- Happ
- Hiddify
- Streisand
- v2RayTun
- v2Box

Проверь, что у узла:

- адрес `nl-001.example.com`
- порт `8443`
- `publicKey` это тот `Public key`, который ты сгенерировал
- `shortId` совпадает
- `serverName` совпадает со значением в профиле

Если всё ок, подключение должно заработать, не трогая старую Amnezia.

## Часть 14. Что делать, если нода offline

Проверь на NL-сервере:

```bash
docker ps
docker compose -f /opt/remnanode/docker-compose.yml logs -f -t
ss -tulpn | grep 2222
```

Проверь между серверами:

- с management VPS должен быть доступен `NL_IP:2222`

Проверь firewall:

- `2222` открыт для IP польского сервера
- для всего остального закрыт

## Часть 15. Что делать, если пользователь не видит хост

Почти всегда это одна из причин:

- профиль не назначен ноде;
- inbound не включён на ноде;
- host создан, но не привязан к правильному inbound;
- inbound не включён в `Default-Squad`;
- пользователь не назначен в этот squad.

## Часть 16. Что делать, если VPN не коннектится

Проверь:

- открыт ли `8443/tcp`;
- `privateKey` и `publicKey` не перепутаны;
- `shortId` совпадает;
- `serverName` совпадает;
- домен `nl-001.example.com` реально резолвится на IP NL-сервера;
- на домене ноды не включён Cloudflare proxy;
- `443` старой Amnezia ты не трогал.

## Часть 17. Как прикрутить Telegram-бота

Бот должен жить на польском management VPS рядом с панелью.

Причина простая:

- там же `API Token` панели;
- там же удобно принимать Tribute webhooks;
- не надо ходить напрямую на NL-ноду;
- вся бизнес-логика живёт в одном месте.

### 17.1. Что будет делать бот

Минимальный MVP:

1. принимает `/start`
2. находит пользователя по `telegram_user_id`
3. проверяет локальный статус подписки
4. если доступ активен:
   - создаёт пользователя в Remnawave или находит существующего
   - отдаёт `subscription URL`
5. если доступа нет:
   - показывает кнопку оплаты

### 17.2. Почему бот не должен проверять Tribute "в онлайне"

Для твоего сценария лучше опираться не на постоянные запросы в Tribute, а на вебхуки:

- `new_subscription`
- `renewed_subscription`
- `cancelled_subscription`

То есть:

- webhook приходит;
- локальная БД обновляет `expires_at`;
- бот доверяет локальной БД.

Это нормально и надёжно.

### 17.3. Где хранить данные бота

Для старта достаточно `SQLite`.

Минимальные таблицы:

- `users`
- `subscriptions`
- `webhook_events`

Примерно такие поля:

#### users

- `telegram_user_id`
- `telegram_username`
- `remnawave_user_id`
- `remnawave_username`
- `subscription_url`
- `status`

#### subscriptions

- `telegram_user_id`
- `tribute_subscription_id`
- `channel_id`
- `expires_at`
- `cancelled`
- `plan`

#### webhook_events

- `event_key`
- `event_name`
- `payload_json`
- `processed_at`

### 17.4. Поток webhook -> бот -> панель

Сценарий:

1. Tribute шлёт `new_subscription`
2. webhook handler валидирует `trbt-signature`
3. по `telegram_user_id` создаётся или обновляется локальная запись
4. бот или backend создаёт пользователя в Remnawave
5. сохраняется `subscription URL`
6. пользователю можно отправить кнопку `Получить VPN`

При `renewed_subscription`:

- просто продлеваешь `expires_at`

При `cancelled_subscription`:

- не отключаешь сразу;
- держишь доступ до `expires_at`

### 17.5. Связка с несколькими нодами потом

Сейчас у тебя одна Remnawave-нода в NL. Потом можешь добавить ещё:

- `DE-001`
- `FI-001`
- `PL-001`

Бот при этом не меняется по архитектуре.

Меняется только логика тарифов:

- базовый тариф видит только `NL`
- другой тариф видит `NL + DE`
- расширенный видит все страны

Это лучше делать через `Squads`, а не вручную по одному пользователю.

## Часть 18. Самый короткий пошаговый план без лишнего

Если совсем сжато, то порядок такой:

1. На польском VPS поставить Docker
2. На польском VPS поставить `Remnawave Panel`
3. На польском VPS поставить `Caddy`
4. Зайти в панель и создать admin
5. В панели создать `Node NL-001` с `Port=2222`
6. На NL-сервере поставить `Remnawave Node`
7. На NL-сервере открыть `8443`, а `2222` разрешить только польскому VPS
8. На NL-сервере сгенерировать REALITY keys
9. В панели создать `Config Profile` с `VLESS + REALITY` на `8443`
10. Назначить профиль ноде
11. Создать Host `Netherlands`
12. Включить inbound в `Default-Squad`
13. Создать тестового пользователя
14. Проверить `Subscription URL`
15. Проверить подключение в клиенте
16. Потом уже ставить Telegram-бота на польский VPS

## Часть 19. Что я рекомендую тебе сейчас

Прямо сейчас не распыляйся.

Сделай в таком порядке:

1. подними панель в Польше
2. добейся, чтобы `NL-001` стала `online`
3. добейся, чтобы тестовый пользователь подключился через `8443`
4. только после этого переходи к Telegram-боту

Иначе начнёшь одновременно дебажить:

- панель;
- ноду;
- REALITY;
- домены;
- бота;
- Tribute.

Это плохая стратегия.

## Источники

- Remnawave Panel install: https://docs.rw/docs/install/remnawave-panel/
- Remnawave Node install: https://docs.rw/docs/install/remnawave-node/
- Remnawave Environment Variables: https://docs.rw/docs/install/environment-variables/
- Remnawave Caddy reverse proxy: https://docs.rw/docs/install/reverse-proxies/caddy/
- Remnawave Nodes: https://docs.rw/docs/learn-en/nodes/
- Remnawave Hosts: https://docs.rw/docs/learn-en/hosts
- Remnawave Config Profiles: https://docs.rw/docs/learn-en/config-profiles
- Remnawave Squads: https://docs.rw/docs/learn-en/squads/
- Remnawave Users: https://docs.rw/docs/learn-en/users/
- Xray REALITY transport: https://xtls.github.io/en/config/transport.html

