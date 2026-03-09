# ---- Stage 1: Build Frontend ----
FROM node:20-alpine AS frontend-build
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ---- Stage 2: Backend + Static Files ----
FROM python:3.11-slim
WORKDIR /app

# Python deps
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Backend code
COPY backend/ ./backend/

# Auth credentials (baked into image for private use)
ENV JWT_SECRET=snowwillow_secret_2026
ENV USER_1_ID=takeshi
ENV USER_1_PW=changeme1
ENV USER_2_ID=user2
ENV USER_2_PW=changeme2
ENV USER_3_ID=user3
ENV USER_3_PW=changeme3
ENV USER_4_ID=user4
ENV USER_4_PW=changeme4

# SQLite DB
COPY data/edinet.db ./data/edinet.db

# Frontend static files (from build stage)
COPY --from=frontend-build /app/frontend/dist ./static

# Expose port
ENV PORT=8080
EXPOSE 8080

# Start: uvicorn serving FastAPI (which also serves static frontend)
CMD ["python", "-m", "uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8080"]
