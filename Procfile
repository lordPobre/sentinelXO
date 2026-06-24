web: gunicorn config.wsgi:application -c gunicorn.conf.py --bind 0.0.0.0:$PORT --workers 2 --timeout 120
worker: celery -A config worker -l info --concurrency=2
beat: celery -A config beat -l info -S django_celery_beat.schedulers:DatabaseScheduler