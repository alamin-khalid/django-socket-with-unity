# Ubuntu 24.04 LTS Hosting Guide

## Your Project Info

| Setting | Value |
|---------|-------|
| Server IP | `103.12.214.243` |
| Project Path | `/home/khalid/apps/app` |
| Redis Port | `16379` (Docker) or `6379` (native) |
| CI/CD | GitHub Actions on `main` branch push |

---

## Architecture

```
Nginx :80/443 → Daphne :8000 → Django + Channels (WebSocket)
                                        │
Celery Beat (scheduler) → Celery Worker → Redis :6379
```

---

## 1. System Setup

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y build-essential python3-dev python3-pip python3-venv redis-server nginx
sudo systemctl enable redis-server nginx
```

---

## 2. Project Setup (First Time)

```bash
mkdir -p /home/khalid/apps/app
cd /home/khalid/apps/app
git clone https://github.com/YOUR_REPO/django-socket-with-unity.git .
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py collectstatic --noinput
```

---

## 3. Environment File

```bash
nano /home/khalid/apps/app/.env
```

```
DJANGO_SECRET_KEY='your-secret-key-here'
DJANGO_DEBUG=False
REDIS_HOST=127.0.0.1
REDIS_PORT=16379
CELERY_BROKER_URL=redis://127.0.0.1:16379/1
CELERY_RESULT_BACKEND=redis://127.0.0.1:16379/2
CELERY_EAGER=False
```

---

## 4. Systemd Services

### Daphne (WebSocket Server)

```bash
sudo nano /etc/systemd/system/daphne.service
```

```ini
[Unit]
Description=Daphne ASGI Server
After=network.target redis-server.service

[Service]
Type=simple
User=khalid
WorkingDirectory=/home/khalid/apps/app
EnvironmentFile=/home/khalid/apps/app/.env
ExecStart=/home/khalid/apps/app/venv/bin/daphne -b 127.0.0.1 -p 8000 server_orchestrator.asgi:application
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

### Celery Worker

```bash
sudo nano /etc/systemd/system/celery-worker.service
```

```ini
[Unit]
Description=Celery Worker
After=network.target redis-server.service

[Service]
Type=simple
User=khalid
WorkingDirectory=/home/khalid/apps/app
EnvironmentFile=/home/khalid/apps/app/.env
ExecStart=/home/khalid/apps/app/venv/bin/celery -A server_orchestrator worker --loglevel=info --concurrency=4
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

### Celery Beat (Scheduler)

```bash
sudo nano /etc/systemd/system/celery-beat.service
```

```ini
[Unit]
Description=Celery Beat Scheduler
After=network.target redis-server.service celery-worker.service

[Service]
Type=simple
User=khalid
WorkingDirectory=/home/khalid/apps/app
EnvironmentFile=/home/khalid/apps/app/.env
ExecStart=/home/khalid/apps/app/venv/bin/celery -A server_orchestrator beat --loglevel=info
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

### Enable Services

```bash
sudo systemctl daemon-reload
sudo systemctl enable daphne celery-worker celery-beat
sudo systemctl start daphne celery-worker celery-beat
```

---

## 5. Nginx Configuration

```bash
sudo nano /etc/nginx/sites-available/django-socket
```

```nginx
upstream daphne {
    server 127.0.0.1:8000;
}

server {
    listen 80;
    server_name 103.12.214.243;

    location /static/ {
        alias /home/khalid/apps/app/staticfiles/;
    }

    location /ws/ {
        proxy_pass http://daphne;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_read_timeout 86400;
        proxy_send_timeout 86400;
    }

    location / {
        proxy_pass http://daphne;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
}
```

```bash
sudo ln -s /etc/nginx/sites-available/django-socket /etc/nginx/sites-enabled/
sudo rm /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl restart nginx
```

---

## 6. CI/CD (GitHub Actions)

Your `.github/workflows/deploy.yml`:

```yaml
name: Deploy Django (Production)

on:
  push:
    branches:
      - main

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: appleboy/ssh-action@v1.0.3
        with:
          host: ${{ secrets.SERVER_HOST }}
          username: ${{ secrets.SERVER_USER }}
          key: ${{ secrets.SERVER_SSH_KEY }}
          port: 6699
          script: |
            set -e
            cd /home/khalid/apps/app
            git pull origin main
            source venv/bin/activate
            pip install -r requirements.txt
            python manage.py migrate --noinput
            python manage.py collectstatic --noinput
            sudo systemctl restart daphne
            sudo systemctl restart celery-worker
            sudo systemctl restart celery-beat
```

> [!IMPORTANT]
> Set these **GitHub Secrets**:
> - `SERVER_HOST` - Your server IP
> - `SERVER_USER` - SSH username (e.g., `khalid`)
> - `SERVER_SSH_KEY` - Your private SSH key

---

## 7. Sudoers (Allow restart without password)

```bash
sudo visudo
```

Add at the end:

```
khalid ALL=(ALL) NOPASSWD: /bin/systemctl restart daphne, /bin/systemctl restart celery-worker, /bin/systemctl restart celery-beat
```

---

## Quick Commands

```bash
# Check service status
sudo systemctl status daphne celery-worker celery-beat

# View logs
sudo journalctl -u daphne -f
sudo journalctl -u celery-worker -f
sudo journalctl -u celery-beat -f

# Restart all
sudo systemctl restart daphne celery-worker celery-beat

# Manual deploy
cd /home/khalid/apps/app && git pull && source venv/bin/activate && pip install -r requirements.txt && python manage.py migrate && sudo systemctl restart daphne celery-worker celery-beat
```

---

## Troubleshooting

| Issue | Check |
|-------|-------|
| WebSocket not connecting | `sudo journalctl -u daphne -f` |
| Scheduled tasks not running | `sudo journalctl -u celery-beat -f` |
| Redis not working | `redis-cli ping` (should return PONG) |
| Planet stuck in error | Tasks auto-recover every 5 seconds now |
