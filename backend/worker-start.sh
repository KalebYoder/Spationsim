#!/bin/sh
set -e

celery -A app.celery_app:celery_app beat --loglevel=info &
celery -A app.celery_app:celery_app worker --loglevel=info
