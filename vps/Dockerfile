FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt qrcode==8.2
# O código fica montado em /app (pasta /opt/radar/app no servidor); o histórico em /data.
CMD ["python", "vps/servico.py"]
