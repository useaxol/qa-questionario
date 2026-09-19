FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# O banco vive em /app/data; monte um volume para preservar o histórico entre
# reinícios — sem histórico o monitor perde a referência de preço padrão.
VOLUME ["/app/data"]

ENV FLIGHTWATCH_DB=/app/data/flightwatch.db \
    FLIGHTWATCH_PORT=10001 \
    PYTHONUNBUFFERED=1

EXPOSE 10001

HEALTHCHECK --interval=60s --timeout=5s --start-period=10s \
  CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:10001/health')"

CMD ["python", "run.py", "serve", "--with-scheduler"]
