FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY requirements.txt .
RUN grep -vE '^(pytest|ruff|playwright)==' requirements.txt > /tmp/requirements.txt \
    && pip install -r /tmp/requirements.txt

COPY app app
COPY isss_bot isss_bot
COPY migrations migrations
COPY scripts scripts
COPY deploy deploy

RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin app
USER app

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-server-header"]
