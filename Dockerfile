# Container-image voor de AI-lab chat-app (dag 3)
# Bouwen in de cloud:  az acr build -r <acr-naam> -t ailab-chat:v1 .
FROM python:3.13-slim

# Geen .pyc-bestanden, logs direct naar stdout (zichtbaar in de log stream)
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000

WORKDIR /app

# Eerst alleen requirements: deze laag wordt gecachet zolang requirements.txt gelijk blijft
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .

# Niet als root draaien (least privilege, ook in een container)
RUN useradd --create-home --uid 10001 appuser
USER appuser

EXPOSE 8000
CMD ["sh", "-c", "gunicorn --bind 0.0.0.0:${PORT} --workers 2 --threads 4 --timeout 120 app:app"]
