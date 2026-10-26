FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv

COPY requirements.txt .
# pytest is only needed for tests; skip it in the image
RUN grep -v '^pytest' requirements.txt > runtime-requirements.txt \
 && pip install --no-cache-dir -r runtime-requirements.txt

COPY app ./app

RUN useradd --system --uid 10001 sentinel
USER sentinel

# Hosts such as Render pass the port in $PORT.
CMD ["sh", "-c", "exec uvicorn app.asgi:app --host 0.0.0.0 --port ${PORT:-8000}"]
