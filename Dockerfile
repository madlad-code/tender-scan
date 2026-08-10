FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src/ src/
RUN pip install --no-cache-dir .

ENV TENDER_SCAN_DB=/data/tender_scan.db
VOLUME /data

EXPOSE 8000
CMD ["tender-scan", "serve", "--host", "0.0.0.0", "--port", "8000"]
