#!/usr/bin/env bash
set -euo pipefail

# Run on an Ubuntu EC2 instance as a user with sudo privileges.
# Set REPOSITORY_URL to the group's GitHub clone URL before running.
REPOSITORY_URL="${REPOSITORY_URL:-}"
BRANCH="${BRANCH:-main}"
APP_DIR="/opt/worktrack/app"

if [[ -z "$REPOSITORY_URL" ]]; then
  echo "Set REPOSITORY_URL to your GitHub repository URL."
  exit 1
fi
if [[ ! -f /etc/worktrack/worktrack.env ]]; then
  echo "Create /etc/worktrack/worktrack.env first (see README.md and .env.example)."
  exit 1
fi

sudo apt-get update
sudo apt-get install -y python3 python3-venv python3-pip nginx git postgresql-client
# Align the host clock and cron schedule with WorkTrack local time (Asia/Manila).
sudo timedatectl set-timezone Asia/Manila
sudo mkdir -p /opt/worktrack /etc/worktrack
# The deployment step below runs as www-data; keep secrets owned by root but group-readable.
sudo chown root:www-data /etc/worktrack/worktrack.env
sudo chmod 640 /etc/worktrack/worktrack.env
sudo chown -R www-data:www-data /opt/worktrack

if [[ -d "$APP_DIR/.git" ]]; then
  sudo -u www-data git -C "$APP_DIR" fetch --all
  sudo -u www-data git -C "$APP_DIR" checkout "$BRANCH"
  sudo -u www-data git -C "$APP_DIR" pull --ff-only origin "$BRANCH"
else
  sudo -u www-data git clone --branch "$BRANCH" "$REPOSITORY_URL" "$APP_DIR"
fi

sudo -u www-data python3 -m venv /opt/worktrack/venv
sudo -u www-data /opt/worktrack/venv/bin/pip install --upgrade pip
sudo -u www-data /opt/worktrack/venv/bin/pip install -r "$APP_DIR/requirements.txt"

sudo install -m 0644 "$APP_DIR/deploy/aws/worktrack.service" /etc/systemd/system/worktrack.service
sudo install -m 0644 "$APP_DIR/deploy/aws/nginx-worktrack.conf" /etc/nginx/sites-available/worktrack
sudo ln -sfn /etc/nginx/sites-available/worktrack /etc/nginx/sites-enabled/worktrack
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t

sudo -u www-data bash -c 'cd /opt/worktrack/app && set -a && source /etc/worktrack/worktrack.env && set +a && if [[ -n "${DB_ADMIN_SECRET_ARN:-}" ]]; then /opt/worktrack/venv/bin/python manage.py provision_rds_app_user; fi && /opt/worktrack/venv/bin/python manage.py migrate --noinput && /opt/worktrack/venv/bin/python manage.py collectstatic --noinput'
sudo systemctl daemon-reload
sudo systemctl enable --now worktrack
sudo systemctl restart nginx
sudo systemctl status worktrack --no-pager
