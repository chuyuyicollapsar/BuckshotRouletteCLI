FROM python:3.14-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV BUCKSHOT_DATA_DIR=/data

ARG EXTRAS=

COPY pyproject.toml README.md ./
COPY buckshot_roulette ./buckshot_roulette
COPY main.py ./

RUN python -m pip install --no-cache-dir --upgrade pip \
    && if [ -n "$EXTRAS" ]; then \
        python -m pip install --no-cache-dir ".[${EXTRAS}]"; \
    else \
        python -m pip install --no-cache-dir .; \
    fi \
    && groupadd --system buckshot \
    && useradd --system --gid buckshot --home-dir /app --no-create-home buckshot \
    && mkdir -p /data \
    && chown -R buckshot:buckshot /app /data

USER buckshot

EXPOSE 8000

CMD ["buckshot-server", "--host", "0.0.0.0", "--port", "8000"]
