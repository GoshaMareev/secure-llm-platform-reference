FROM ghcr.io/data-privacy-stack/presidio-analyzer@sha256:ae8f6f111ac2f04e3fec552f7f80edd0dcbfa2dd69ee1b9e030475be31669885
USER root
COPY infra/presidio/requirements-ru.lock /tmp/requirements-ru.lock
RUN python -m pip install --require-hashes -r /tmp/requirements-ru.lock
RUN python -c "import hashlib,urllib.request; u='https://github.com/explosion/spacy-models/releases/download/ru_core_news_sm-3.8.0/ru_core_news_sm-3.8.0-py3-none-any.whl'; b=urllib.request.urlopen(u).read(); assert hashlib.sha256(b).hexdigest()=='69978d47b43e2c4f329bebdb155e8e9d3861bba1a58ba25551419dae7d7e07fc'; open('/tmp/ru_core_news_sm-3.8.0-py3-none-any.whl','wb').write(b)" \
 && python -m pip install --no-deps /tmp/ru_core_news_sm-3.8.0-py3-none-any.whl \
 && rm /tmp/ru_core_news_sm-3.8.0-py3-none-any.whl
COPY infra/presidio/analyzer.yaml /etc/presidio/analyzer.yaml
COPY infra/presidio/nlp.yaml /etc/presidio/nlp.yaml
COPY infra/presidio/recognizers.yaml /etc/presidio/recognizers.yaml
ENV ANALYZER_CONF_FILE=/etc/presidio/analyzer.yaml
ENV NLP_CONF_FILE=/etc/presidio/nlp.yaml
ENV RECOGNIZER_REGISTRY_CONF_FILE=/etc/presidio/recognizers.yaml
