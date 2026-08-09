# syntax=docker/dockerfile:1

FROM python:3.12-slim AS builder

WORKDIR /build

COPY requirements.txt .
RUN mkdir -p /install \
    && pip install --no-cache-dir --prefix=/install -r requirements.txt


FROM python:3.12-slim AS runtime

WORKDIR /app

RUN useradd --create-home --uid 1000 --shell /usr/sbin/nologin appuser \
    && chown appuser:appuser /app

COPY --from=builder /install /usr/local

USER appuser

CMD ["python", "-c", "print('container started')"]
