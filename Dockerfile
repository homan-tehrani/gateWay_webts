FROM reg.masafiranian.ir/python:3.9
RUN mkdir -p /app
WORKDIR /app

COPY requirements.txt /
RUN pip install -r /requirements.txt

COPY . /app

EXPOSE 8000
CMD ["uvicorn", "main:app", "--reload","--host", "0.0.0.0", "--port", "80"]
