FROM python:3.10
RUN mkdir -p /app
WORKDIR /app

COPY requirements.txt /
RUN pip install -r /requirements.txt

COPY . /app

CMD ["uvicorn", "main:app", "--reload","--host", "0.0.0.0", "--port", "80" , "--log-config" ,  "log_conf.yaml"]
