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

# Auth credentials (SHA-256 hashed passwords)
ENV JWT_SECRET=snowwillow_secret_2026
ENV USER_1_ID=takeshi
ENV USER_1_PW=4bdf3fba58c956fc3991a1fde84929223f968e2853de596e49ae80a91499609b
ENV USER_2_ID=user2
ENV USER_2_PW=3b88361ba1f309f57872fb49b7c97998329879669822ecd3ad70273e3db1f472
ENV USER_3_ID=user3
ENV USER_3_PW=09968e1849abb64dc96915bfca550db81de2ed95349d836875e8fc9341cc8f19
ENV USER_4_ID=user4
ENV USER_4_PW=6d3352d6a6513fe8db54cb8750284ed7b8bb7a573ecdbe96a78fef41f8eeda87

# SQLite DB
COPY data/edinet.db ./data/edinet.db

# Frontend static files (from build stage)
COPY --from=frontend-build /app/frontend/dist ./static

# Expose port
ENV PORT=8080
EXPOSE 8080

# Start: uvicorn serving FastAPI (which also serves static frontend)
CMD ["python", "-m", "uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8080"]
