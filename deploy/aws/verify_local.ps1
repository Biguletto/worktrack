$ErrorActionPreference = 'Stop'

# Run from the folder that contains manage.py on Windows PowerShell.
if (-not (Test-Path '.venv')) {
    python -m venv .venv
}

& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt
& .\.venv\Scripts\python.exe manage.py check
& .\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
& .\.venv\Scripts\python.exe manage.py test eqrApp --settings=django_employee_qr.test_settings
& .\.venv\Scripts\python.exe -m compileall -q eqrApp django_employee_qr

Write-Host 'Local WorkTrack verification completed successfully.' -ForegroundColor Green
