FROM arm32v7/python:3-slim
WORKDIR /usr/src/app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
#RUN apk upgrade --update && \
#apk add --no-cache make build-base libffi libffi-dev openssl openssl-dev && \
#pip install --no-cache-dir -r requirements.txt && \
#apk del build-base libffi-dev openssl-dev

COPY . .

RUN python setup.py install

WORKDIR /root

ENTRYPOINT [ "orbot" ]
