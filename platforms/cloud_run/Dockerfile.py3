FROM python:3.7
COPY cloud_run/requirements.txt /requirements.txt
RUN pip install --no-cache-dir -r /requirements.txt
RUN pip install --no-cache-dir orjson
COPY cloud_run/serviceaccount.json /tmp/gcpkeys.json
ENV GOOGLE_APPLICATION_CREDENTIALS /tmp/gcpkeys.json
WORKDIR /app
COPY gae_standard/py27/big.json \
     gae_standard/py37/falcon_main.py \
     gae_standard/py37/fastapi_main.py \
     gae_standard/py37/helper.py \
     gae_standard/py37/helper_db.py \
     gae_standard/py37/helper_ndb.py \
     ./
CMD exec gunicorn --workers 1 --worker-class gevent --worker-connections 80 --bind :$PORT falcon_main:app --error-logfile=- --log-level warning
