FROM python:3.13-alpine3.22

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN apk update && apk upgrade && \
    rm -rf /var/cache/apk/* && \
    pip install --no-cache-dir pdm

COPY pyproject.toml pdm.lock ./
RUN pdm sync && \
    pdm cache clear


COPY . /app

