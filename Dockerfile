FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 FAMILY_FINANCE_DIR=/app
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
COPY alembic.ini ./
COPY migrations ./migrations
RUN pip install --no-cache-dir .
USER 1000:1000
CMD ["family-finance-sync", "--env", "sandbox", "ais"]
