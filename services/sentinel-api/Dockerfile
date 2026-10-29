FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv

COPY requirements.txt .
# pytest is only needed for tests; skip it in the image
RUN grep -v '^pytest' requirements.txt > runtime-requirements.txt \
 && pip install --no-cache-dir -r runtime-requirements.txt

COPY app ./app
# The research model's metadata (results, calibration) shown on the dashboard's ML model page;
# the large .joblib artifacts stay out of the image.
COPY models/root_cause_v2.json ./models/

RUN useradd --system --uid 10001 sentinel
USER sentinel

# Hosts such as Render pass the port in $PORT. The client address behind the host's proxy comes from
# SENTINEL_TRUSTED_PROXY_HOPS (the rightmost X-Forwarded-For entries), not from uvicorn's proxy
# headers, which with every proxy trusted would believe a client-supplied header.
CMD ["sh", "-c", "exec uvicorn app.asgi:app --host 0.0.0.0 --port ${PORT:-8000} --no-proxy-headers"]
