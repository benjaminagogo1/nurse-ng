FROM python:3.12-slim-bookworm

WORKDIR /opt/nurse-ng
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    NURSE_NG_ENVIRONMENT=production NURSE_NG_DEBUG=false \
    NURSE_NG_SESSION_HTTPS_ONLY=true \
    NURSE_NG_REQUIRED_WORKERS=recruitment,reels,notifications \
    NURSE_NG_AVATAR_DIR=/var/lib/nurse-ng/avatars \
    NURSE_NG_COMMUNITY_MEDIA_DIR=/var/lib/nurse-ng/community \
    NURSE_NG_EVIDENCE_DIR=/var/lib/nurse-ng/evidence \
    NURSE_NG_BACKUP_DIR=/var/lib/nurse-ng/backups \
    NURSE_NG_COMMUNITY_MALWARE_SCAN_MODE=required \
    NURSE_NG_REELS_FFMPEG=/usr/bin/ffmpeg

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates clamav ffmpeg \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.lock ./
RUN python -m pip install --no-cache-dir -r requirements.lock
COPY app ./app
COPY migrations ./migrations
COPY deploy ./deploy
COPY alembic.ini ./
RUN groupadd --gid 10001 nurse \
    && useradd --uid 10001 --gid nurse --home-dir /var/lib/nurse-ng --no-create-home nurse \
    && mkdir -p /var/lib/nurse-ng/avatars /var/lib/nurse-ng/community \
       /var/lib/nurse-ng/evidence /var/lib/nurse-ng/backups \
    && chown -R nurse:nurse /var/lib/nurse-ng \
    && chmod -R u=rwX,go= /var/lib/nurse-ng
USER nurse
EXPOSE 8000
ENTRYPOINT ["python", "deploy/start.py"]
CMD ["web"]
