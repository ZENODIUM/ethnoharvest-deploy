FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends curl unzip libexpat1 && rm -rf /var/lib/apt/lists/*
RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user PATH=/home/user/.local/bin:$PATH PYTHONUNBUFFERED=1
WORKDIR /home/user/app
COPY --chown=user requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt
COPY --chown=user . .
# WorldClim is fetched from its official host at build time rather than redistributed in this repository.
RUN mkdir -p data/raw/worldclim/wc2.1_10m_bio \
 && curl -fsSL -o /tmp/wc.zip https://geodata.ucdavis.edu/climate/worldclim/2_1/base/wc2.1_10m_bio.zip \
 && unzip -q /tmp/wc.zip -d data/raw/worldclim/wc2.1_10m_bio && rm /tmp/wc.zip
ENV FRONTEND_DIST=/home/user/app/frontend_dist
EXPOSE 7860
CMD ["sh", "start.sh"]
