FROM python:3.14-slim
WORKDIR /usr/local/app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8000
RUN almbic upgrade head
CMD ["./start.sh"]