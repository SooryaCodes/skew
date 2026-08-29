# The trading loop needs a persistent process, so this deploys as a container
# rather than to serverless. See docs/02-TECH-STACK.md.
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY skew/ ./skew/
COPY data/ ./data/
COPY pyproject.toml .

# Never baked into the image. Supplied by the platform's env var store.
ENV ALPACA_BASE_URL=https://paper-api.alpaca.markets

RUN useradd --create-home --uid 10001 skew && chown -R skew:skew /app
USER skew

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).status==200 else 1)"

CMD ["sh", "-c", "uvicorn skew.api:app --host 0.0.0.0 --port ${PORT:-8000}"]
