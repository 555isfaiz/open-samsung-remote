FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY samsung_remote ./samsung_remote
COPY wsgi.py .

# Non-root; /data holds the pairing token (mounted as a volume in k8s).
RUN useradd -m app && mkdir /data && chown app /data
USER app

ENV CONFIG_PATH=/config/config.yaml
EXPOSE 5000

CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "1", "--timeout", "30", "wsgi:app"]
