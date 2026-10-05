FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
    bash ca-certificates curl git python3 tmux nginx-light tini util-linux libstdc++6 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --uid 1000 --home-dir /data/home --shell /bin/bash agent
COPY install-ttyd.sh /tmp/install-ttyd.sh
RUN bash /tmp/install-ttyd.sh && rm /tmp/install-ttyd.sh
# Download from Google's official installer; the installer verifies the payload SHA512.
# The upstream release is rolling, not pinned by this experimental add-on.
RUN curl --fail --location --retry 3 https://antigravity.google/cli/install.sh -o /tmp/install-agy.sh \
    && bash /tmp/install-agy.sh --dir /opt/antigravity \
    && test -x /opt/antigravity/agy && rm /tmp/install-agy.sh
COPY run.sh services.sh session.sh /usr/local/bin/
COPY nginx.conf /etc/nginx/antigravity.conf
RUN chmod 755 /usr/local/bin/run.sh /usr/local/bin/services.sh /usr/local/bin/session.sh
ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/run.sh"]
