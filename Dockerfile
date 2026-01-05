FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    STREAMLIT_HOST_DATA=/data

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY streamlit_host /app/streamlit_host


EXPOSE 8080

EXPOSE 8500

CMD ["python", "-m", "streamlit_host.run_all"]


