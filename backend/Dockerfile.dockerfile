# backend/Dockerfile
FROM python:3.11-slim

# Prevent Python from writing pyc files to disc and force stdout buffering
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Set the working directory
WORKDIR /app

# Install system dependencies required for psycopg2 and pandas
RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy the requirements and install them
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the backend application
COPY . .

# Expose the WebSocket port
EXPOSE 8000

# Boot the industrial server
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000"]