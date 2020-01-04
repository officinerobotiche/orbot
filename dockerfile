FROM python:3-slim
WORKDIR /usr/src/app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN python setup.py install

WORKDIR /root

ENTRYPOINT [ "orbot" ]