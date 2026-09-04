FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    SURF_DATA=/app/data \
    PORT=8080

WORKDIR /app

COPY pyproject.toml README.md ./
COPY surf ./surf
COPY data ./data

RUN pip install --no-cache-dir ".[remote]"

EXPOSE 8080

CMD ["surf-mcp-http"]
