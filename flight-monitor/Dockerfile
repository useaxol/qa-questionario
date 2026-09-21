FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# O banco vive em /app/data. A referência de preço vem da tabela de benchmark
# (que está no código), então o app funciona com o volume vazio — mas a série
# do índice e a recalibração vivem aqui. Monte um volume para preservá-las.
VOLUME ["/app/data"]

ENV FLIGHTWATCH_DB=/app/data/flightwatch.db \
    FLIGHTWATCH_PORT=10001 \
    PYTHONUNBUFFERED=1

EXPOSE 10001

HEALTHCHECK --interval=60s --timeout=5s --start-period=10s \
  CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:10001/health')"

CMD ["python", "run.py", "serve", "--with-scheduler"]
