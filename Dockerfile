FROM python:3.9-slim

# gcc est nécessaire sur certaines architectures pour compiler psutil
# si aucune roue (wheel) précompilée n'est disponible.
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Fichier vide pour que Docker traite bien le point de montage suivant comme un
# fichier (et non un dossier) lors d'un `docker run -v ...:/app/monitor.db`.
RUN touch monitor.db

EXPOSE 8000

# Un seul worker : le planificateur APScheduler et la base SQLite ne supportent pas
# plusieurs workers Gunicorn en parallèle (voir DEPLOYMENT_UBUNTU.md).
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)" || exit 1

CMD ["gunicorn", "--workers", "1", "--bind", "0.0.0.0:8000", "app:app"]
