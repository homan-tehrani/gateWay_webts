FROM docker.arvancloud.ir/python:3.12

RUN mkdir -p /app
WORKDIR /app

COPY requirements.txt /

# Upgrade pip
RUN pip install --trusted-host liara.ir \
    -i https://package-mirror.liara.ir/repository/pypi/simple \
    --upgrade pip

# Install requirements
RUN pip install --trusted-host liara.ir \
    -i https://package-mirror.liara.ir/repository/pypi/simple \
    -r /requirements.txt

COPY . /app


# CMD ["tail","-f","/dev/null"]

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "80" ,"--workers","4"]
#CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "80" ,"--workers","4", "--log-config", "log_conf.yaml"]
#CMD ["uvicorn", "main:app", "--reload", "--host", "0.0.0.0", "--port", "80"]
