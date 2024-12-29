# Use an official Python image
FROM python:3.10-slim

WORKDIR /app

COPY . .

RUN pip install --no-cache-dir flask seleniumbase

EXPOSE 8080

CMD ["python", "app.py"]