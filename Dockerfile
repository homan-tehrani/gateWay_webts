FROM docker.arvancloud.ir/python:3.12

ENV PYTHONUNBUFFERED=1

RUN mkdir -p /app
WORKDIR /app

COPY requirements.txt /

RUN pip install --trusted-host liara.ir \
    -i https://package-mirror.liara.ir/repository/pypi/simple \
    --upgrade pip

RUN pip install --trusted-host liara.ir \
    -i https://package-mirror.liara.ir/repository/pypi/simple \
    -r /requirements.txt

COPY . /app

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "80", "--workers", "1"]
