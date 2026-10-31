FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md ./
COPY hooplab ./hooplab
RUN pip install --no-cache-dir .
ENV HOOPLAB_DATA=/data
VOLUME /data
EXPOSE 8000
CMD ["uvicorn", "hooplab.api:app", "--host", "0.0.0.0", "--port", "8000"]
