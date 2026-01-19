FROM python:3.10-slim

WORKDIR /app
COPY . .

RUN pip install --no-cache-dir -r requirements.txt

# Instala o Chromium e dependências do Playwright
RUN python -m playwright install --with-deps chromium

CMD ["python", "app.py"]
