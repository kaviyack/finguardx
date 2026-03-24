FROM python:3.12-slim

WORKDIR /app

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl gcc && rm -rf /var/lib/apt/lists/*

# Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app
COPY . .

# Pre-train model on build (cached in volume)
RUN python -c "import sys; sys.path.insert(0,'risk-engine'); \
    from risk_engine import train; train()" || true

EXPOSE 8080

CMD ["python", "app.py"]
