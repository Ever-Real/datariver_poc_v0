FROM apache/airflow:3.3.0-python3.12

USER root
RUN install -d -o 50000 -g 0 -m 0770 /opt/airflow/auth /opt/airflow/logs
USER 50000:0
