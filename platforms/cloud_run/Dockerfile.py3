FROM python:3
COPY cloud_run/requirements.txt /requirements.txt
RUN pip install --no-binary :all: --no-cache-dir -r /requirements.txt
RUN pip install --no-cache-dir aioify fastapi orjson
ENV GAE_VERSION gevent
COPY cloud_run/serviceaccount.json /tmp/gcpkeys.json
ENV GOOGLE_APPLICATION_CREDENTIALS /tmp/gcpkeys.json
WORKDIR /app
COPY gae_standard/py27/big.json \
     gae_standard/py37/falcon_main.py \
     gae_standard/py37/helper.py \
     gae_standard/py37/helper_db.py \
     gae_standard/py37/helper_ndb.py \
     ./
CMD exec gunicorn --worker-class gevent --workers 2 --bind :$PORT falcon_main:app --error-logfile=- --log-level warning
