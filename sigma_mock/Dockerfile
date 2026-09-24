FROM php:8.4-apache
COPY public/index.php /var/www/html/index.php
COPY public/.htaccess /var/www/html/.htaccess
RUN a2enmod rewrite \
    && sed -i 's/AllowOverride None/AllowOverride All/g' /etc/apache2/apache2.conf \
    && apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*
ENV SIGMA_API_TOKEN=dev-sigma-token
ENV SIGMA_STORE=/tmp/sigma_mock_store.json
EXPOSE 80
