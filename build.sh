#!/usr/bin/env bash
# Render Build Script — runs automatically on every deployment

set -o errexit  # Exit immediately if any command fails

echo "==> Installing Python dependencies..."
pip install -r requirements.txt

echo "==> Collecting static files..."
python manage.py collectstatic --no-input

echo "==> Running database migrations..."
python manage.py migrate --no-input

echo "==> Build complete!"
