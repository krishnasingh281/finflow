FROM python:3.11-slim

# set working directory
WORKDIR /app

# install dependencies first (better Docker layer caching this way)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# copy the entire backend
COPY backend/ .

# collect static files so whitenoise can serve them
RUN python manage.py collectstatic --noinput

# Cloud Run expects the app to listen on port 8080
ENV PORT=8080
EXPOSE 8080

# run migrations at startup, then launch gunicorn
CMD python manage.py migrate && gunicorn finflow.wsgi:application --bind 0.0.0.0:$PORT --workers 2 --timeout 60
