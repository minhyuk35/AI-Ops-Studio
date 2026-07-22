FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY services/core-api /app/services/core-api
WORKDIR /app/services/core-api
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

