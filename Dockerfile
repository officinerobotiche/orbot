FROM python:3-alpine
WORKDIR /usr/src/app

COPY requirements.txt ./
RUN apk upgrade --update && \
apk add --no-cache make build-base libffi libffi-dev openssl openssl-dev && \
pip install --no-cache-dir -r requirements.txt && \
apk del build-base libffi-dev openssl-dev

COPY . .

RUN python setup.py install

WORKDIR /root

ENTRYPOINT [ "orbot" ]
