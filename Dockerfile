FROM maksim1111/seleniumbase:latest

WORKDIR /app

COPY . .

RUN pip install --no-cache-dir flask flask-cors

EXPOSE 5000

CMD ["python3", "app.py"]
