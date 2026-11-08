FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 SMS_ENV=production SMS_DATA_DIR=/data
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN useradd -r -u 10001 sms && mkdir /data && chown sms /data
USER sms
VOLUME /data
EXPOSE 8000
# SMS_SECRET_KEY must be supplied at run time (docker run -e SMS_SECRET_KEY=...)
CMD ["sh", "-c", "python run.py"]
