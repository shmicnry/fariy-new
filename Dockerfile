FROM python:3.12-slim
WORKDIR /app
ENV FAIRY_WEB_ROOT=/app/apps/web
COPY pyproject.toml requirements.lock ./
COPY server server
COPY apps/web apps/web
RUN pip install --no-cache-dir -r requirements.lock && pip install --no-cache-dir --no-deps . && useradd -m fairy && mkdir var && chown fairy var
USER fairy
EXPOSE 8000
CMD ["uvicorn", "fairy.app:app", "--host", "0.0.0.0", "--port", "8000"]
