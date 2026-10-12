# The Blocky updater (see updater.py and the README): Docker CLI + compose, git, Python.
FROM docker:27-cli
RUN apk add --no-cache git python3 \
    && (docker compose version || apk add --no-cache docker-cli-compose) \
    && git config --system --add safe.directory '*'
COPY updater.py /updater.py
CMD ["python3", "-u", "/updater.py"]
