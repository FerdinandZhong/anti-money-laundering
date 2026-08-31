FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates && \
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
    apt-get install -y --no-install-recommends nodejs && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY 03_application/frontend/package*.json 03_application/frontend/
RUN cd 03_application/frontend && npm ci

COPY . .
RUN cd 03_application/frontend && npm run build

EXPOSE 8100

CMD ["python", "start_app.py"]
