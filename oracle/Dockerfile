FROM python:3.12-slim

# coincurve requires build tools for its C extension
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libssl-dev \
        pkg-config \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8080

CMD ["python", "main.py"]
