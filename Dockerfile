FROM python:3.13-slim AS builder

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

FROM python:3.13-slim

RUN groupadd -r gametracker && useradd -r -g gametracker gametracker \
    && mkdir -p /data && chown gametracker:gametracker /data

WORKDIR /app
COPY --from=builder /install /usr/local
COPY app ./app

ENV DATABASE_URL=sqlite:////data/gametracker.db \
    PYTHONUNBUFFERED=1

USER gametracker
VOLUME /data
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=3)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
