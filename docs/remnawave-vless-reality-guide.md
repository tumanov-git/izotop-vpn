# Remnawave: EU Direct + RU Bridge on VLESS + REALITY

Этот гайд делает ровно то, что тебе нужно:

- у пользователей есть `EU Direct` для обычного времени;
- у пользователей есть `RU Bridge` для белых списков;
- транзит `RU -> EU` тоже построен на `VLESS + REALITY`, без `Shadowsocks`.

Итоговая схема:

```text
Обычный режим:
  client -> EU Direct -> internet

Белые списки:
  client -> RU Bridge -> EU Exit -> internet
```

## Важная оговорка

То, что ниже, частично является прямым применением официальных материалов, а частично аккуратной сборкой из них:

- Remnawave официально показывает server-side routing на двух нодах и отдельно пишет, что вместо `Shadowsocks` можно использовать `VLESS`.
- Xray официально документирует `REALITY`, `XHTTP`, `raw`, `target`, `password`.
- Твой файл `/Users/izotop/md thing/VLESS-chain-REMNAWAVE-guide.md` дает практический шаблон именно для связки `RU -> EU` через `VLESS + REALITY + XHTTP`.

Вывод:

- сама идея и объектная модель в Remnawave здесь официальные;
- конкретный transit-конфиг `RU -> EU` через `VLESS + REALITY + XHTTP` это инженерная сборка по Xray docs + твоему файлу.

## Можно ли держать panel и node на одном сервере

Да. Remnawave в quick start прямо пишет: Node можно ставить `on the same server (not recommended) or on a different server`.

Для твоего кейса это нормально так:

- текущий EU сервер: `Panel + EU Node`
- отдельный RU сервер: `RU Node`

Новая отдельная EU VM не нужна.

## Что будет в panel

Тебе понадобятся:

- 2 ноды:
  - `EU-Node`
  - `RU-Bridge`
- 2 config profile:
  - `EU Main Profile`
  - `RU Bridge Profile`
- 3 internal squad:
  - `Users Direct`
  - `Users Bridge`
  - `Bridge Service`
- 1 service user:
  - `bridge-service`
- 2 host:
  - `EU Direct`
  - `RU WhiteList`

## Шаг 1. Подготовка серверов

На обоих серверах:

```bash
sudo apt update
sudo apt full-upgrade -y
sudo apt install -y ca-certificates curl jq htop ufw unzip git logrotate
curl -fsSL https://get.docker.com | sudo sh
sudo systemctl enable docker
sudo systemctl start docker
sudo usermod -aG docker "$USER"
```

Перелогинься после добавления в docker group.

Безопасный минимум sysctl:

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

## Шаг 2. EU сервер: panel + node

### 2.1. Panel

Если panel уже стоит и работает, этот шаг пропусти.

Если нет:

```bash
sudo mkdir -p /opt/remnawave
sudo chown -R "$USER":"$USER" /opt/remnawave
cd /opt/remnawave
curl -o docker-compose.yml https://raw.githubusercontent.com/remnawave/backend/refs/heads/main/docker-compose-prod.yml
curl -o .env https://raw.githubusercontent.com/remnawave/backend/refs/heads/main/.env.sample
```

Потом сгенерируй секреты и отредактируй `.env`.

Минимум исправить:

- `FRONT_END_DOMAIN=panel.example.com`
- `SUB_PUBLIC_DOMAIN=subs.example.com/api/sub`

Запуск:

```bash
cd /opt/remnawave
docker compose up -d
```

### 2.2. EU Node

В panel:

1. `Nodes -> Management -> +`
2. Создай `EU-Node`
3. `Address`: публичный IP или домен EU сервера
4. `Node Port`: `2222`
5. Нажми `Copy docker-compose.yml`

На EU сервере:

```bash
sudo mkdir -p /opt/remnanode
sudo mkdir -p /var/log/remnanode
sudo chown -R "$USER":"$USER" /opt/remnanode
cd /opt/remnanode
sudo chown -R "$USER":"$USER" /opt/remnanode
nano docker-compose.yml
```

Вставь compose от panel и запусти:

```bash
docker compose up -d
docker compose logs -f -t
```

## Шаг 3. RU сервер: node only

В panel:

1. `Nodes -> Management -> +`
2. Создай `RU-Bridge`
3. `Address`: белый IP RU сервера
4. `Node Port`: `2222`
5. Нажми `Copy docker-compose.yml`

На RU сервере:

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

## Шаг 4. Firewall

### EU

```bash
sudo ufw allow 22/tcp
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw allow from <RU_PUBLIC_IP> to any port 443 proto tcp
sudo ufw allow from <PANEL_PUBLIC_IP> to any port 2222 proto tcp
sudo ufw enable
```

### RU

```bash
sudo ufw allow 22/tcp
sudo ufw allow 443/tcp
sudo ufw allow from <EU_PUBLIC_IP> to any port 2222 proto tcp
sudo ufw enable
```

Примечание:

- `2222` это API ноды для panel, не клиентский порт.
- Клиенты заходят на `443`.

## Шаг 5. EU Main Profile

Этот профиль нужен EU ноде и делает два дела:

- принимает прямых пользователей через `EU_DIRECT_VLESS`
- принимает transit от RU bridge через `EU_CHAIN_IN`

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
      "tag": "EU_CHAIN_IN",
      "listen": "0.0.0.0",
      "port": 8443,
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
          "privateKey": "<EU_CHAIN_PRIVATE_KEY>",
          "shortIds": ["<EU_CHAIN_SHORT_ID>"]
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

### Почему здесь отдельный `EU_CHAIN_IN`

Так чище:

- direct-пользователи и transit-связка не мешают друг другу
- можно дать service user доступ только к `EU_CHAIN_IN`
- можно отдельно менять `shortId`, ключи и даже path

## Шаг 6. RU Bridge Profile

Это ключевой профиль. Пользователи подключаются к RU, а RU решает:

- российское -> `DIRECT`
- остальное -> `TO_EU_EXIT`

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
      "protocol": "vless",
      "settings": {
        "vnext": [
          {
            "address": "<EU_PUBLIC_ADDRESS>",
            "port": 8443,
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
          "password": "<EU_CHAIN_PUBLIC_KEY>",
          "shortId": "<EU_CHAIN_SHORT_ID>"
        },
        "xhttpSettings": {
          "mode": "packet-up",
          "path": "/api/v1/update"
        }
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

## Шаг 7. Что откуда взять

### На EU node

Сгенерируй две пары ключей REALITY:

```bash
docker exec remnanode xray x25519
docker exec remnanode xray x25519
```

Первая пара:

- `EU_REALITY_PRIVATE_KEY`
- `EU_REALITY_PUBLIC_KEY`

Вторая пара:

- `EU_CHAIN_PRIVATE_KEY`
- `EU_CHAIN_PUBLIC_KEY`

Сделай два short id:

- `EU_SHORT_ID`
- `EU_CHAIN_SHORT_ID`

Пример формата:

```text
8c12a4f0b6d9e211
```

### На RU node

Сгенерируй еще одну пару:

```bash
docker exec remnanode xray x25519
```

Это:

- `RU_REALITY_PRIVATE_KEY`
- `RU_REALITY_PUBLIC_KEY`

И свой short id:

- `RU_SHORT_ID`

### Service user

Создай пользователя `bridge-service`.

Важно:

- это не клиентский пользователь
- его нельзя раздавать людям
- ему нужен доступ только к inbound `EU_CHAIN_IN`

В Remnawave:

1. Создай `Internal Squad` с названием `Bridge Service`
2. Включи в нем только inbound `EU_CHAIN_IN`
3. Создай user `bridge-service`
4. Дай ему:
   - `Data Limit = 0`
   - expiry далеко в будущем
   - squad `Bridge Service`
5. Открой `Detailed Info`
6. Скопируй `VLESS UUID`

Это и будет `BRIDGE_SERVICE_UUID`.

## Шаг 8. Assign profile и squads

### EU node

На `EU-Node` назначь `EU Main Profile`.

При выборе активных inbound включи:

- `EU_DIRECT_VLESS`
- `EU_CHAIN_IN`

### RU node

На `RU-Bridge` назначь `RU Bridge Profile`.

Включи inbound:

- `RU_BRIDGE_VLESS`

### Пользовательские squads

Создай:

- `Users Direct` -> inbound `EU_DIRECT_VLESS`
- `Users Bridge` -> inbound `RU_BRIDGE_VLESS`

Если хочешь, чтобы в подписке у обычного пользователя были оба варианта, дай ему оба squad.

## Шаг 9. Hosts

### EU Direct

Создай host:

- `Remark`: `EU Direct`
- `Inbound`: `EU_DIRECT_VLESS`
- `Address`: лучше домен, например `eu.example.com`
- `Port`: `443`

### RU WhiteList

Создай host:

- `Remark`: `RU WhiteList`
- `Inbound`: `RU_BRIDGE_VLESS`
- `Address`: белый IP RU-ноды или домен на него
- `Port`: `443`

Для RU host можно использовать IP, если белый именно этот IP и домен не нужен.

## Шаг 10. Почему `packet-up` на транзите

Это уже не из Remnawave docs, а вывод из XHTTP discussion и твоего файла.

Что известно из официальных материалов Xray:

- XHTTP при `REALITY` по умолчанию в `auto` тяготеет к `stream-one`
- `packet-up` рекомендуется как наиболее совместимый режим для прохождения HTTP middleboxes

Почему я оставил на `RU -> EU` именно:

```json
"mode": "packet-up"
```

Потому что у тебя именно сценарий с российской фильтрацией и проблемными сетями, а не “чистая” датацентр-лента.

Если начнутся странные upload-проблемы у части приложений, это первый кандидат на эксперимент:

- попробовать `mode: "auto"`
- либо оставить `packet-up` только для bridge, а не для direct

## Шаг 11. Проверка

### Проверка нод

В panel:

- `Nodes -> Management`
- обе ноды должны быть `online`

### Проверка direct

Подключись профилем `EU Direct`:

```bash
curl https://ifconfig.me
```

Должен быть IP EU сервера.

### Проверка bridge

Подключись профилем `RU WhiteList`:

```bash
curl https://ifconfig.me
```

Тоже должен быть IP EU сервера, а не RU.

### Проверка логов

На нодах:

```bash
docker logs remnanode -f --tail 100
tail -f /var/log/remnanode/error.log
tail -f /var/log/remnanode/access.log
```

## Практические замечания

### 1. RU direct-routing не делает трафик “невидимым”

Даже если RU нода выводит `.ru` трафик через `DIRECT`, сам факт того, что клиент подключен к RU bridge, оператор все равно видит. Поэтому лучший UX для пользователей:

- `EU Direct` как основной профиль в обычное время
- `RU WhiteList` как запасной профиль под белые списки

### 2. Лучше не мешать direct и chain на одном inbound

Технически можно пытаться заставить одну EU reality-входную точку обслуживать и direct, и transit. Но для Remnawave заметно чище и безопаснее развести:

- `EU_DIRECT_VLESS`
- `EU_CHAIN_IN`

### 3. Порты `443` и `8443`

Я использовал:

- `443` для `EU_DIRECT_VLESS`
- `8443` для `EU_CHAIN_IN`

Это сделано специально, чтобы direct и chain не мешались.

Если хочешь прятать transit тоже за `443`, это возможно, но там уже придется аккуратно разводить по path, SNI, fallback или reverse proxy, и это отдельная более хрупкая схема.

## Источники

- Remnawave Quick start: [docs.rw/docs/overview/quick-start](https://docs.rw/docs/overview/quick-start/)
- Remnawave server-side routing: [docs.rw/docs/learn-en/server-routing](https://docs.rw/docs/learn-en/server-routing/)
- Xray transport / REALITY: [xtls.github.io/en/config/transport.html](https://xtls.github.io/en/config/transport.html)
- XHTTP discussion: [github.com/XTLS/Xray-core/discussions/4113](https://github.com/XTLS/Xray-core/discussions/4113)
- Твой исходный файл: `/Users/izotop/md thing/VLESS-chain-REMNAWAVE-guide.md`
