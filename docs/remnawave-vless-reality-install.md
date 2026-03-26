# Remnawave + VLESS + REALITY на 1 VPS

Дата: 2026-03-21

Этот гайд рассчитан на твой сценарий:

- один VPS в Нидерландах;
- ставим `Remnawave Panel` и `Remnawave Node`;
- основной VPN-протокол: `VLESS + REALITY`;
- хотим потом подключить Telegram-бота, который будет выдавать ключи через API панели.

Документ специально написан в формате обычного Markdown, чтобы открыть его в Obsidian без доработок.

## Что важно понять заранее

`Remnawave Panel` и `Remnawave Node` это разные вещи:

- `Panel` хранит пользователей, ноды, шаблоны и отдаёт API;
- `Node` запускает `Xray-core` и реально гоняет трафик;
- сама панель `Xray-core` не содержит.

Официальная документация Remnawave отдельно отмечает, что:

- панель обязательно должна стоять за reverse proxy;
- сервисы панели не надо открывать наружу напрямую;
- ноду желательно ставить на отдельный сервер, но для старта можно и на тот же VPS.

## Главный подводный камень: порт 443

Если у тебя один IP и один VPS, то есть конфликт:

- панель обычно живёт на `443` через `Caddy`/`Nginx`;
- `VLESS + REALITY` тоже чаще всего хотят поставить на `443`.

На одном IP это нельзя просто так занять одновременно двумя разными сервисами.

### Практичный стартовый вариант

Для первого запуска используй так:

- панель: `443`;
- `VLESS + REALITY`: `8443`.

Это не самый "красивый" порт для клиента, но зато схема простая и без плясок.

### Если хочешь REALITY именно на 443

Тогда нужен один из вариантов:

- второй публичный IP на том же сервере;
- отдельный сервер под панель;
- отдельный домен и отдельная машина под панель.

Для старта я рекомендую не усложнять и оставить `REALITY` на `8443`.

## Целевая схема

```text
internet
  |
  |-- panel.example.com:443 --> Caddy/Nginx --> Remnawave Panel (127.0.0.1:3000)
  |
  |-- nl.example.com:8443 --> Remnawave Node / Xray (VLESS + REALITY)
  |
  \-- node API port (например 2222) доступен только с IP этого же сервера
```

## Что понадобится

- Ubuntu 22.04/24.04 или Debian 12;
- root-доступ по SSH;
- домен для панели, например `panel.example.com`;
- домен или поддомен для VPN-хоста, например `nl.example.com`;
- Docker и Docker Compose plugin;
- минимум 2 GB RAM, лучше 4 GB.

## DNS

Создай записи:

- `panel.example.com` -> IP твоего VPS
- `nl.example.com` -> IP твоего VPS

Если используешь Cloudflare:

- для `panel.example.com` можно оставить проксирование, если у тебя регионально всё нормально;
- для `nl.example.com` под `REALITY` лучше использовать `DNS only`, без оранжевой тучки.

## Шаг 1. Подготовь сервер

Подключись по SSH и обнови систему:

```bash
apt update
apt upgrade -y
timedatectl set-timezone Europe/Amsterdam
```

Установи базовые пакеты:

```bash
apt install -y curl ca-certificates gnupg ufw jq openssl
```

## Шаг 2. Поставь Docker

Официальная команда из документации Remnawave:

```bash
curl -fsSL https://get.docker.com | sh
```

Проверь:

```bash
docker --version
docker compose version
```

## Шаг 3. Открой нужные порты

Пример через `ufw`:

```bash
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw allow 8443/tcp
ufw enable
```

`Node Port` для связи панели и ноды наружу открывать не надо. Если панель и нода стоят на одном сервере, этот порт можно ограничить локальным IP и firewall.

## Шаг 4. Установи Remnawave Panel

Официальная установка панели:

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

Потом открой `/opt/remnawave/.env` и руками проверь минимум эти поля:

```env
FRONT_END_DOMAIN=panel.example.com
SUB_PUBLIC_DOMAIN=panel.example.com/api/sub
```

Пока так нормально. Отдельную публичную subscription page можно вынести позже.

Запусти панель:

```bash
cd /opt/remnawave
docker compose up -d
docker compose logs -f -t
```

Важно:

- сама панель должна слушать только локально, через `127.0.0.1`;
- наружу её отдаёт reverse proxy.

## Шаг 5. Поставь reverse proxy для панели

Для простоты используй `Caddy`.

Создай `Caddyfile`:

```bash
mkdir -p /opt/remnawave/caddy
cd /opt/remnawave/caddy
```

Содержимое `/opt/remnawave/caddy/Caddyfile`:

```caddy
https://panel.example.com {
    reverse_proxy * http://remnawave:3000
}

:443 {
    tls internal
    respond 204
}
```

Содержимое `/opt/remnawave/caddy/docker-compose.yml`:

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

После этого панель должна открыться по адресу:

```text
https://panel.example.com
```

## Шаг 6. Создай первого администратора

При первом входе:

- открой `https://panel.example.com`;
- зарегистрируй первого пользователя;
- этот пользователь автоматически станет `super-admin`.

Сразу после входа:

- включи 2FA/Passkey если будешь активно пользоваться панелью;
- зайди в `Remnawave Settings`;
- создай `API Token` для будущего Telegram-бота.

## Шаг 7. Создай ноду в панели

Перед установкой контейнера ноды удобнее сначала создать ноду в UI, потому что Remnawave сам генерирует `docker-compose.yml`.

В панели:

1. Открой `Nodes -> Management`
2. Нажми `Create new node`
3. Заполни:
   - `Country`: Netherlands
   - `Internal name`: например `NL-001`
   - `Address`: IP сервера или `nl.example.com`
   - `Port`: например `2222`
4. Нажми `Copy docker-compose.yml`

`Port` здесь это не порт VPN-клиентов. Это внутренний порт, по которому панель общается с Remnawave Node API.

## Шаг 8. Поставь Remnawave Node

Официальная схема:

```bash
mkdir -p /opt/remnanode
cd /opt/remnanode
```

Вставь туда `docker-compose.yml`, который скопировал из панели.

Потом запусти:

```bash
cd /opt/remnanode
docker compose up -d
docker compose logs -f -t
```

Если панель и нода стоят на одном VPS:

- оставляй `Address` у ноды либо публичным IP, либо `nl.example.com`;
- `Node Port` ограничь firewall так, чтобы к нему ходил только этот же сервер.

Пример ограничения через `ufw`, если `Node Port = 2222`:

```bash
ufw allow from 127.0.0.1 to any port 2222 proto tcp
ufw deny 2222/tcp
```

Если панель достукивается до ноды по публичному IP, а не по localhost, тогда вместо `127.0.0.1` укажи адрес, с которого панель реально приходит.

## Шаг 9. Сгенерируй ключи для REALITY

Тебе нужны:

- `privateKey`
- `publicKey`
- `shortId`

Если внутри контейнера ноды есть бинарник `xray`, можно сделать так:

```bash
docker exec -it remnanode xray x25519
```

Сохрани результат. Это даст пару `Private key` и `Public key`.

`shortId` можно сделать, например, 8-16 hex-символов:

```bash
openssl rand -hex 8
```

## Шаг 10. Создай Config Profile под VLESS + REALITY

В панели:

1. Открой `Config Profiles`
2. Создай новый профиль, например `VLESS-REALITY-NL`
3. Вставь профиль вручную или загрузи шаблон и отредактируй inbound

Ниже минимальный рабочий пример для старта. Значения замени на свои:

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
          "privateKey": "REPLACE_WITH_REALITY_PRIVATE_KEY",
          "shortIds": [
            "REPLACE_WITH_SHORT_ID"
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

### Что означают ключевые поля

- `port: 8443` - порт для клиентов VPN;
- `target` - сайт, под который маскируется REALITY;
- `serverNames` - допустимые SNI для клиента;
- `privateKey` - приватный ключ REALITY;
- `shortIds` - набор допустимых `shortId`.

### Важное замечание по REALITY

Xray предупреждает: если аутентификация REALITY не прошла, трафик форвардится в `target`.

Из этого следуют правила:

- не ставь в `target` что попало;
- не используй бездумно сайты за CDN, если не понимаешь последствия;
- для старта выбери стабильный TLS endpoint, который нормально отвечает на `443`.

## Шаг 11. Привяжи профиль к ноде

Теперь вернись в `Nodes -> Management`:

1. Открой `NL-001`
2. Выбери `Change Profile`
3. Назначь профиль `VLESS-REALITY-NL`
4. Включи inbound `VLESS_TCP_REALITY`
5. Сохрани

## Шаг 12. Создай Host

`Host` в Remnawave это точка входа, которую увидит клиент в подписке.

Открой `Hosts` и создай хост:

- `Name`: `Netherlands`
- `Address`: `nl.example.com`
- `Port`: `8443`
- `Visible`: `enabled`
- привяжи нужную ноду
- включи inbound `VLESS_TCP_REALITY`

## Шаг 13. Проверь Internal Squad

Даже если профиль и хост созданы, пользователь не увидит inbound, пока он не разрешён в squad.

Открой:

- `Internal Squads`
- `Default-Squad`

И убедись, что там включён inbound `VLESS_TCP_REALITY`.

## Шаг 14. Создай тестового пользователя

Открой `Users` и создай пользователя:

- имя: например `test-nl-01`
- срок: по желанию
- лимит трафика: по желанию
- squad: `Default-Squad`

После создания:

- скопируй `Subscription URL`;
- открой его в браузере;
- проверь, что там виден хост `Netherlands`.

## Шаг 15. Подключи клиент

Импортируй `Subscription URL` в клиент:

- Happ
- Hiddify
- Streisand
- v2RayTun
- v2Box
- Clash Verge Rev, если используешь соответствующий шаблон подписки

Для `VLESS + REALITY` клиенту важны:

- адрес сервера: `nl.example.com`
- порт: `8443`
- UUID пользователя
- `publicKey` от REALITY
- `shortId`
- `serverName`
- `flow`: обычно `xtls-rprx-vision`
- fingerprint: обычно `chrome`

`publicKey` берётся из пары, которую ты получил командой `x25519`.

## Шаг 16. Подготовь панель к боту

Для будущего Telegram-бота тебе понадобится:

- `Remnawave API Token`;
- URL панели;
- понимание, как бот будет находить пользователя;
- лучше сразу договориться о схеме имени, например:
  - `tg_123456789`
  - или `vpn_tribute_123456789`

На старте бот может делать очень простую вещь:

1. получает `telegram_user_id`;
2. находит пользователя в своей базе или в Remnawave;
3. если пользователя нет, создаёт;
4. если доступ активен, возвращает subscription URL;
5. если доступа нет, отправляет кнопку на оплату.

## Рекомендуемая схема для твоего старта

Под твой текущий кейс я бы шёл так:

1. Панель и нода на одном VPS
2. `REALITY` на `8443`
3. Один хост `Netherlands`
4. Один профиль `VLESS + REALITY`
5. Один squad `Default-Squad`
6. Потом Telegram-бот поверх `Remnawave API`

Это самое короткое расстояние от "сервер пустой" до "пользователь получил рабочую подписку".

## Что я бы не делал на первом запуске

- не пытался бы сразу посадить и панель, и REALITY на `443` на одном IP;
- не городил бы отдельную subscription page до первого рабочего подключения;
- не добавлял бы сразу 5 нод и сложный routing;
- не завязывал бы бизнес-логику только на ручную выдачу `vless://` ссылок без API панели.

## Быстрый чек-лист после установки

- панель открывается по `https://panel.example.com`
- первый admin создан
- API token выпущен
- нода `NL-001` online
- профиль `VLESS_TCP_REALITY` назначен
- host `Netherlands` виден
- inbound включён в `Default-Squad`
- у тестового пользователя копируется subscription URL
- клиент реально подключается

## Типовые проблемы

### Панель открывается, но нода offline

Проверь:

- запущен ли контейнер `remnanode`;
- совпадает ли `Node Port`;
- не режет ли firewall порт API ноды;
- верный ли `SECRET_KEY` в `docker-compose.yml`, который сгенерировала панель.

### Пользователь есть, но хостов в подписке нет

Обычно причина одна из трёх:

- inbound не включён в `Internal Squad`;
- host не привязан к inbound;
- профиль не назначен ноде.

### Клиент не подключается по REALITY

Проверь:

- `publicKey`/`privateKey` не перепутаны;
- совпадает ли `shortId`;
- совпадает ли `serverName`;
- открыт ли порт `8443`;
- не включён ли Cloudflare proxy на VPN-домене.

## Источники

- Remnawave Panel install: https://docs.rw/docs/install/remnawave-panel/
- Remnawave Node install: https://docs.rw/docs/install/remnawave-node/
- Remnawave Requirements: https://docs.rw/docs/install/requirements
- Remnawave Quick Start: https://docs.rw/docs/overview/quick-start/
- Remnawave Caddy reverse proxy: https://docs.rw/docs/install/reverse-proxies/caddy/
- Remnawave Hosts: https://docs.rw/docs/learn-en/hosts/
- Remnawave Users: https://docs.rw/docs/learn-en/users/
- Remnawave Config Profiles: https://docs.rw/docs/learn-en/config-profiles
- Xray transport / REALITY: https://xtls.github.io/en/config/transport.html
- Xray VLESS inbound: https://xtls.github.io/en/config/inbounds/vless.html

## Что делать дальше

После того как сервер реально поднимется и тестовый пользователь подключится, следующий логичный шаг:

- подключить Telegram-бота к `Remnawave API`;
- решить, идём ли мы через `Tribute creator subscriptions`, `Tribute digital products` или `Tribute Shop API`;
- только потом автоматизировать выдачу/продление доступа.
