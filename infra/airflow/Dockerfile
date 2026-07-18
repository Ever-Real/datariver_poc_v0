FROM apache/airflow:3.3.0-python3.12

USER root
RUN install -d -o 50000 -g 0 -m 0770 /opt/airflow/auth /opt/airflow/logs
COPY --chown=50000:0 scripts/generate_semiconductor_seed.py /opt/datariver/scripts/generate_semiconductor_seed.py
USER 50000:0
RUN pip install --no-cache-dir asyncpg==0.31.0 httpx==0.28.1
