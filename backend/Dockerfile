FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py assistant.py ai_features.py ai_service.py ai_context.py schedule.py ./
COPY static ./static
COPY data/db.json ./data/db.json
ENV PORT=5000 DATA_DIR=/app/data PYTHONUNBUFFERED=1
EXPOSE 5000
VOLUME ["/app/data"]
CMD ["flask", "--app", "app", "run", "--host", "0.0.0.0", "--port", "5000"]
