FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-spa \
    libtesseract-dev \
    poppler-utils \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libgomp1 \
    gcc \
    g++ \
    curl \
    unzip \
    && rm -rf /var/lib/apt/lists/*

ENV ORACLE_HOME=/opt/oracle/instantclient_21_12
ENV LD_LIBRARY_PATH=$ORACLE_HOME:$LD_LIBRARY_PATH
ENV PATH=$ORACLE_HOME:$PATH

RUN mkdir -p /opt/oracle && cd /opt/oracle && \
    curl -fSL -o basic.zip https://download.oracle.com/otn_software/linux/instantclient/2112000/instantclient-basic-linux.x64-21.12.0.0.0dbru.zip && \
    curl -fSL -o sdk.zip https://download.oracle.com/otn_software/linux/instantclient/2112000/instantclient-sdk-linux.x64-21.12.0.0.0dbru.zip && \
    unzip -q basic.zip && unzip -q sdk.zip && \
    rm basic.zip sdk.zip && \
    echo /opt/oracle/instantclient_21_12 > /etc/ld.so.conf.d/oracle-instantclient.conf && \
    ldconfig

WORKDIR /app

COPY pyproject.toml poetry.lock* ./
RUN pip install --no-cache-dir poetry && \
    poetry config virtualenvs.create false && \
    poetry install --only=main --no-interaction --no-root && \
    pip install --no-cache-dir pytest pytest-asyncio && \
    rm -rf /root/.cache/pip

COPY app ./app
COPY wsdl ./wsdl

RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]