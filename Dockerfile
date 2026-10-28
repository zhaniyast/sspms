# 1) сборка React-интерфейса
FROM node:22-slim AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
ENV VITE_DEMO_MODE=false
RUN npm run build

# 2) сервер Flask + модель
FROM python:3.12-slim
WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY backend/ backend/
COPY models/model_db10.joblib models/model_db10.joblib
COPY --from=web /web/dist frontend/dist
ENV BEHIND_PROXY=1 COOKIE_SECURE=1 HOST=0.0.0.0
CMD gunicorn "backend.app:create_app()" --bind 0.0.0.0:${PORT:-8000} --workers 1 --threads 4 --timeout 120
