#!/usr/bin/env bash
set -euo pipefail

# Run from the folder that contains manage.py.
if [[ ! -d .venv ]]; then
  python3 -m venv .venv
fi
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py test eqrApp --settings=django_employee_qr.test_settings
python -m compileall -q eqrApp django_employee_qr

echo "Local WorkTrack verification completed successfully."
