FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ .

RUN python manage.py collectstatic --noinput

# Render assigns PORT dynamically — do NOT hardcode 8080
EXPOSE 10000

CMD python manage.py migrate && gunicorn finflow.wsgi:application --bind 0.0.0.0:${PORT:-10000} --workers 2 --timeout 60