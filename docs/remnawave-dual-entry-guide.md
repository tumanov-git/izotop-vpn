# Remnawave: EU Direct + RU Bridge

Этот гайд сводит вместе:

- официальную документацию Remnawave;
- официальную документацию Xray;
- практические заметки из файла `/Users/izotop/md thing/VLESS-chain-REMNAWAVE-guide.md`.

Цель: дать пользователям два способа входа в одной панели:

- `EU Direct` для обычного времени;
- `RU Bridge` для режима белых списков.

Итоговая схема:

```text
Обычный режим:
  client -> EU Direct node -> Internet

Режим белых списков:
  client -> RU Bridge node -> EU Exit node -> Internet
```

## Короткий ответ

- Новая отдельная EU-нода тебе не нужна, если текущая EU-нода уже рабочая.
- Текущая EU-машина может быть и `direct entry`, и `exit` для bridge-схемы.
- `Panel` и `Node` на одном сервере ставить можно, но Remnawave прямо пишет, что это `not recommended`.
- Для production под твою задачу нормальный компромисс такой:
  - текущий EU-сервер: `Panel + EU Node`;
  - новый RU-сервер: `RU Node`.

## Что важно по актуальным докам

В текущих Xray-доках часть старых полей переименована:

- `network: "tcp"` теперь корректнее писать как `network: "raw"`; старое имя все еще алиас.
- в `realitySettings` серверное поле теперь называется `target`; старое `dest` все еще алиас.
- в `realitySettings` клиентское поле теперь называется `password`; старое `publicKey` все еще алиас.

Если копируешь старые конфиги из интернета, это не всегда ошибка, но лучше уже писать новыми именами.

## Архитектура

### EU-сервер

На текущем EU-сервере держим:

- `Remnawave Panel`
- `Remnawave Node`
- публичный inbound для обычных пользователей: `EU_DIRECT_VLESS`
- transit inbound для bridge-связки: `EU_TRANSIT_SS`

### RU-сервер

На RU-сервере держим:

- `Remnawave Node`
- публичный inbound для пользователей под белыми списками: `RU_BRIDGE_VLESS`
- routing:
  - `.ru` и `geoip:ru` -> `DIRECT`
  - остальное -> в `EU_TRANSIT_SS`

### Почему здесь transit через Shadowsocks

Это самый близкий к официальному гайду Remnawave вариант для server-side routing между двумя нодами. Он проще в поддержке и меньше зависит от нюансов transport-слоя.

Твой исходный файл предлагает более агрессивный вариант `RU -> EU` через `VLESS + REALITY + XHTTP`. Это можно сделать, но как стартовую production-конфигурацию я рекомендую именно docs-aligned вариант с transit через `Shadowsocks`, а `Reality + XHTTP` оставить как advanced-upgrade.

## Базовая подготовка серверов

На обеих VM:

```bash
sudo apt update
sudo apt full-upgrade -y
sudo apt install -y ca-certificates curl jq htop ufw unzip git logrotate
curl -fsSL https://get.docker.com | sudo sh
sudo systemctl enable docker
sudo systemctl start docker
sudo usermod -aG docker "$USER"
```

После этого перелогинься.

Если хочешь BBR и безопасный минимум sysctl:

```bash
sudo tee /etc/sysctl.d/99-remnawave.conf >/dev/null <<'EOF'
net.core.default_qdisc = fq
net.ipv4.tcp_congestion_control = bbr
net.ipv4.tcp_fastopen = 3
net.ipv4.ip_forward = 1
net.core.rmem_max = 16777216
net.core.wmem_max = 16777216
EOF

sudo sysctl --system
```

## Шаг 1. EU-сервер: Panel + Node

### 1.1. Panel

Если panel еще не установлена, ставь по текущей оф. инструкции:

```bash
sudo mkdir -p /opt/remnawave
sudo chown -R "$USER":"$USER" /opt/remnawave
cd /opt/remnawave
curl -o docker-compose.yml https://raw.githubusercontent.com/remnawave/backend/refs/heads/main/docker-compose-prod.yml
curl -o .env https://raw.githubusercontent.com/remnawave/backend/refs/heads/main/.env.sample
```

Сгенерируй секреты:

```bash
sed -i "s/^JWT_AUTH_SECRET=.*/JWT_AUTH_SECRET=$(openssl rand -hex 64)/" .env
sed -i "s/^JWT_API_TOKENS_SECRET=.*/JWT_API_TOKENS_SECRET=$(openssl rand -hex 64)/" .env
sed -i "s/^METRICS_PASS=.*/METRICS_PASS=$(openssl rand -hex 64)/" .env
sed -i "s/^WEBHOOK_SECRET_HEADER=.*/WEBHOOK_SECRET_HEADER=$(openssl rand -hex 64)/" .env
pw=$(openssl rand -hex 24) && sed -i "s/^POSTGRES_PASSWORD=.*/POSTGRES_PASSWORD=$pw/" .env && sed -i "s|^\(DATABASE_URL=\"postgresql://postgres:\)[^\@]*\(@.*\)|\1$pw\2|" .env
```

Потом открой `.env` и обязательно поправь:

- `FRONT_END_DOMAIN`
- `SUB_PUBLIC_DOMAIN`

Пример:

```env
FRONT_END_DOMAIN=panel.example.com
SUB_PUBLIC_DOMAIN=subs.example.com/api/sub
```

Запуск:

```bash
cd /opt/remnawave
docker compose up -d
```

### 1.2. Reverse proxy

Panel по оф. докам надо ставить за reverse proxy и не светить наружу контейнерные сервисы напрямую. Для простоты можно использовать Caddy или Nginx.

Минимум по firewall на EU:

```bash
sudo ufw allow 22/tcp
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
```

### 1.3. EU Node

В Panel:

1. `Nodes -> Management -> +`
2. Создай ноду `EU-Node`
3. В `Address` укажи публичный IP EU-сервера или стабильный домен, который резолвится в этот IP
4. `Node Port`: `2222`
5. Нажми `Copy docker-compose.yml`

На EU-сервере:

```bash
sudo mkdir -p /opt/remnanode
sudo mkdir -p /var/log/remnanode
sudo chown -R "$USER":"$USER" /opt/remnanode
cd /opt/remnanode
nano docker-compose.yml
```

Вставь compose, который дала panel. Если хочешь пример с логами:

```yaml
services:
  remnanode:
    container_name: remnanode
    hostname: remnanode
    image: remnawave/node:latest
    restart: always
    network_mode: host
    environment:
      - NODE_PORT=2222
      - SECRET_KEY="<SECRET_FROM_PANEL>"
    volumes:
      - '/var/log/remnanode:/var/log/remnanode'
```

Запуск:

```bash
docker compose up -d
docker compose logs -f -t
```

После этого вернись в panel, нажми `Next`, выбери профиль и заверши создание ноды.

### 1.4. Логи ноды и logrotate

```bash
sudo tee /etc/logrotate.d/remnanode >/dev/null <<'EOF'
/var/log/remnanode/*.log {
  size 50M
  rotate 5
  compress
  missingok
  notifempty
  copytruncate
}
EOF
```

## Шаг 2. RU-сервер: Node only

В Panel:

1. `Nodes -> Management -> +`
2. Создай ноду `RU-Bridge`
3. `Address`: белый публичный IP RU-сервера
4. `Node Port`: `2222`
5. Нажми `Copy docker-compose.yml`

На RU-сервере:

```bash
sudo mkdir -p /opt/remnanode
sudo mkdir -p /var/log/remnanode
sudo chown -R "$USER":"$USER" /opt/remnanode
cd /opt/remnanode
nano docker-compose.yml
```

Вставь compose от panel и запусти:

```bash
docker compose up -d
docker compose logs -f -t
```

Firewall на RU:

```bash
sudo ufw allow 22/tcp
sudo ufw allow 443/tcp
sudo ufw allow from <EU_PANEL_PUBLIC_IP> to any port 2222 proto tcp
sudo ufw enable
```

## Шаг 3. Объекты в Panel

Тебе понадобятся:

- 2 Config Profiles:
  - `EU Main Profile`
  - `RU Bridge Profile`
- 3 Internal Squads:
  - `Users Direct`
  - `Users Bridge`
  - `Bridge Service`
- 1 service user:
  - `bridge-service`
- 2 Hosts:
  - `EU Direct`
  - `RU WhiteList`

## Шаг 4. Config Profile для EU

Это основной профиль для EU-ноды. В нем два inbound:

- `EU_DIRECT_VLESS` для обычных пользователей
- `EU_TRANSIT_SS` для трафика из RU-ноды

```json
{
  "log": {
    "loglevel": "warning",
    "access": "/var/log/remnanode/access.log",
    "error": "/var/log/remnanode/error.log"
  },
  "inbounds": [
    {
      "tag": "EU_DIRECT_VLESS",
      "listen": "0.0.0.0",
      "port": 443,
      "protocol": "vless",
      "settings": {
        "clients": [],
        "decryption": "none"
      },
      "streamSettings": {
        "network": "xhttp",
        "security": "reality",
        "realitySettings": {
          "target": "www.microsoft.com:443",
          "serverNames": ["www.microsoft.com"],
          "privateKey": "<EU_REALITY_PRIVATE_KEY>",
          "shortIds": ["<EU_SHORT_ID>"]
        },
        "xhttpSettings": {
          "mode": "auto",
          "path": "/api/v1/update"
        }
      },
      "sniffing": {
        "enabled": true,
        "destOverride": ["http", "tls", "quic"]
      }
    },
    {
      "tag": "EU_TRANSIT_SS",
      "listen": "0.0.0.0",
      "port": 9999,
      "protocol": "shadowsocks",
      "settings": {
        "clients": [],
        "network": "tcp,udp"
      },
      "sniffing": {
        "enabled": true,
        "destOverride": ["http", "tls", "quic"]
      }
    }
  ],
  "outbounds": [
    {
      "tag": "DIRECT",
      "protocol": "freedom",
      "settings": {
        "domainStrategy": "UseIPv4v6"
      }
    },
    {
      "tag": "BLOCK",
      "protocol": "blackhole"
    }
  ],
  "routing": {
    "domainStrategy": "IPIfNonMatch",
    "rules": [
      {
        "type": "field",
        "ip": ["geoip:private"],
        "outboundTag": "BLOCK"
      },
      {
        "type": "field",
        "domain": ["geosite:private"],
        "outboundTag": "BLOCK"
      }
    ]
  }
}
```

### Откуда взять значения

- `EU_REALITY_PRIVATE_KEY`: `docker exec remnanode xray x25519`
- `EU_SHORT_ID`: любая четная hex-строка длиной до 16 символов, например `8c12a4f0b6d9e211`

## Шаг 5. Config Profile для RU Bridge

Этот профиль основан на:

- server-side routing из Remnawave docs;
- transport-части из твоего исходного файла.

```json
{
  "log": {
    "loglevel": "warning",
    "access": "/var/log/remnanode/access.log",
    "error": "/var/log/remnanode/error.log"
  },
  "dns": {
    "servers": [
      {
        "address": "https://1.1.1.1/dns-query",
        "domains": ["geosite:geolocation-!cn"]
      },
      {
        "address": "https://dns.yandex.net/dns-query",
        "domains": ["geosite:category-ru", "regexp:\\.ru$"]
      },
      "localhost"
    ]
  },
  "inbounds": [
    {
      "tag": "RU_BRIDGE_VLESS",
      "listen": "0.0.0.0",
      "port": 443,
      "protocol": "vless",
      "settings": {
        "clients": [],
        "decryption": "none"
      },
      "streamSettings": {
        "network": "raw",
        "security": "reality",
        "realitySettings": {
          "target": "vkvideo.ru:443",
          "serverNames": ["vkvideo.ru", "vk.com"],
          "privateKey": "<RU_REALITY_PRIVATE_KEY>",
          "shortIds": ["<RU_SHORT_ID>"]
        }
      },
      "sniffing": {
        "enabled": true,
        "destOverride": ["http", "tls", "quic"]
      }
    }
  ],
  "outbounds": [
    {
      "tag": "TO_EU_EXIT",
      "protocol": "shadowsocks",
      "settings": {
        "servers": [
          {
            "address": "<EU_NODE_PUBLIC_ADDRESS>",
            "port": 9999,
            "method": "chacha20-ietf-poly1305",
            "password": "<BRIDGE_SERVICE_SS_PASSWORD>"
          }
        ]
      }
    },
    {
      "tag": "DIRECT",
      "protocol": "freedom",
      "settings": {
        "domainStrategy": "UseIPv4"
      }
    },
    {
      "tag": "BLOCK",
      "protocol": "blackhole"
    }
  ],
  "routing": {
    "domainStrategy": "IPIfNonMatch",
    "rules": [
      {
        "type": "field",
        "ip": ["geoip:private"],
        "outboundTag": "BLOCK"
      },
      {
        "type": "field",
        "domain": ["geosite:private"],
        "outboundTag": "BLOCK"
      },
      {
        "type": "field",
        "ip": ["geoip:ru"],
        "outboundTag": "DIRECT"
      },
      {
        "type": "field",
        "domain": [
          "geosite:category-ru",
          "regexp:\\.ru$",
          "geosite:yandex",
          "full:vk.com",
          "full:gosuslugi.ru",
          "full:mail.ru",
          "full:ok.ru",
          "full:sberbank.ru",
          "full:rutube.ru",
          "full:ozon.ru",
          "full:wildberries.ru"
        ],
        "outboundTag": "DIRECT"
      },
      {
        "type": "field",
        "inboundTag": ["RU_BRIDGE_VLESS"],
        "outboundTag": "TO_EU_EXIT"
      }
    ]
  }
}
```

## Шаг 6. Internal Squads и service user

### 6.1. Bridge Service squad

Создай `Internal Squad`:

- `Bridge Service`
- включи только inbound `EU_TRANSIT_SS`

### 6.2. Service user

Создай пользователя:

- username: `bridge-service`
- `Data Limit = 0`
- `Expiry Date` далеко в будущем, например `2099`
- назначь squad `Bridge Service`

Затем:

1. Открой карточку пользователя
2. `More actions -> Detailed Info`
3. Скопируй `SS Password`

Это и есть значение для `<BRIDGE_SERVICE_SS_PASSWORD>`.

### 6.3. User squads

Создай два обычных Internal Squad:

- `Users Direct` -> включи `EU_DIRECT_VLESS`
- `Users Bridge` -> включи `RU_BRIDGE_VLESS`

Обычным пользователям назначай оба squad, если хочешь, чтобы в подписке сразу были оба варианта входа.

## Шаг 7. Hosts

### 7.1. Host для обычного времени

Создай Host:

- `Remark`: `EU Direct`
- `Inbound`: `EU_DIRECT_VLESS`
- `Address`: лучше домен, например `eu.example.com`
- `Port`: `443`

Для этого host лучше использовать домен, потому что docs Remnawave рекомендуют домен вместо raw IP: при смене IP пользователям не надо заново обновлять подписки вручную.

### 7.2. Host для белых списков

Создай Host:

- `Remark`: `RU WhiteList`
- `Inbound`: `RU_BRIDGE_VLESS`
- `Address`: белый IP RU-ноды или домен, который резолвится в него
- `Port`: `443`

В `Advanced Options`, если хочешь явно задать значения:

- `SNI`: `vkvideo.ru`
- `Fingerprint`: `chrome`

Если у тебя нет стабильного домена на RU IP, здесь допустимо использовать raw IP.

## Шаг 8. Проверка

### 8.1. Проверка нод

В panel:

- `Nodes -> Management`
- обе ноды должны быть `online`

### 8.2. Проверка direct

Возьми обычного пользователя, импортируй подписку и выбери host `EU Direct`.

Проверь:

```bash
curl https://ifconfig.me
```

Должен быть IP EU-сервера.

### 8.3. Проверка bridge

Выбери host `RU WhiteList`.

Проверь:

```bash
curl https://ifconfig.me
```

Снаружи тоже должен быть IP EU-сервера, а не RU.

### 8.4. Логи

На нодах:

```bash
docker logs remnanode -f --tail 100
tail -f /var/log/remnanode/error.log
tail -f /var/log/remnanode/access.log
```

## Важный нюанс про сплит

Из твоего исходного файла есть полезная практическая мысль: если российский трафик отправлять в VPN даже с `DIRECT` выходом на RU-ноды, оператор все равно видит, что телефон шлет запросы к российским сайтам через IP bridge-ноды.

Поэтому:

- серверный routing на RU-нode нужен как страховка;
- но лучший вариант для части клиентов это клиентский split-tunneling, где `.ru` ресурсы идут вообще мимо VPN.

Иначе говоря:

- `EU Direct` нужен для обычного времени;
- `RU WhiteList` нужен для режима ограничений;
- не стоит насильно заставлять всех пользователей всегда сидеть через `RU Bridge`.

## Advanced upgrade: заменить SS transit на VLESS + REALITY + XHTTP

Это можно сделать, если тебе нужен именно transport из твоего исходного файла.

Логика такая:

- в EU-профиле оставляешь `EU_DIRECT_VLESS`
- создаешь service user `bridge-service` с доступом к этому inbound
- на RU-нode вместо `TO_EU_EXIT` через Shadowsocks делаешь `protocol: "vless"` outbound на EU:443

Скелет outbound для RU:

```json
{
  "tag": "TO_EU_EXIT",
  "protocol": "vless",
  "settings": {
    "vnext": [
      {
        "address": "<EU_NODE_PUBLIC_ADDRESS>",
        "port": 443,
        "users": [
          {
            "id": "<BRIDGE_SERVICE_UUID>",
            "encryption": "none"
          }
        ]
      }
    ]
  },
  "streamSettings": {
    "network": "xhttp",
    "security": "reality",
    "realitySettings": {
      "fingerprint": "chrome",
      "serverName": "www.microsoft.com",
      "password": "<EU_REALITY_PUBLIC_KEY>",
      "shortId": "<EU_SHORT_ID>"
    },
    "xhttpSettings": {
      "mode": "packet-up",
      "path": "/api/v1/update"
    }
  }
}
```

Это уже не буквально повторяет оф. routing guide Remnawave, а является выводом из:

- механики `Config Profiles` в Remnawave;
- transport-документации Xray;
- твоего исходного файла.

Поэтому я бы сначала запускал схему с `Shadowsocks transit`, а уже потом, если она работает и тебе нужен именно `xHTTP` между нодами, делал upgrade.

## Источники

- Remnawave Quick start: https://docs.rw/docs/overview/quick-start/
- Remnawave Panel install: https://docs.rw/docs/install/remnawave-panel/
- Remnawave Node install: https://docs.rw/docs/install/remnawave-node/
- Remnawave Config Profiles: https://docs.rw/docs/learn-en/config-profiles
- Remnawave Hosts: https://docs.rw/docs/learn-en/hosts
- Remnawave Server-Side Routing: https://docs.rw/docs/learn-en/server-routing/
- Xray transport / REALITY: https://xtls.github.io/en/config/transport.html
- Твой исходный файл: `/Users/izotop/md thing/VLESS-chain-REMNAWAVE-guide.md`
