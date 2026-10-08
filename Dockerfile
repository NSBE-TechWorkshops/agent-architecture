# One image runs BOTH the API server and the terminal UI. docker-compose picks which command to run.
FROM python:3.12-slim

# Don't write .pyc files, and print logs immediately (so `docker compose logs` is live).
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Copy ONLY requirements first. Docker caches each step ("layer"), so as long as
# requirements.txt is unchanged, rebuilds skip the slow install and take seconds.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Now copy the code. Changing code only invalidates layers from here down.
COPY app ./app
COPY tui ./tui
COPY data ./data
COPY scripts ./scripts

# Run as a normal user instead of root (a basic container security habit).
RUN useradd --create-home appuser && chown -R appuser /app
USER appuser

EXPOSE 8000

# Default command = the API server. 0.0.0.0 means "accept connections from outside the container".
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
