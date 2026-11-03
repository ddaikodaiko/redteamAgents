# Executor container for the benchmark: the LLM agent's commands are run here
# (docker exec agent-runner ...). Lightweight Debian + the offensive toolset the
# agent uses to attack the deliberately-vulnerable targets on owasp-net.
#
# This container stays INSIDE the isolated lab network. agent_runner.py's scope
# guard additionally refuses any command targeting a host outside 172.20.0.0/16,
# so the toolset here can only reach the lab's own training apps.
FROM debian:bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive

# Toolset. Matches ALLOWED_TOOLS in harness/agent_runner.py.
# (nikto is not packaged on Debian bookworm; installed from source below. perl +
#  SSL modules are its runtime deps and are not in the slim base image.)
RUN apt-get update && apt-get install -y --no-install-recommends \
        sqlmap \
        nmap \
        curl \
        wget \
        jq \
        python3 \
        python3-pip \
        git \
        ca-certificates \
        dirb \
        netcat-openbsd \
        iputils-ping \
        perl \
        libnet-ssleay-perl \
        libio-socket-ssl-perl \
    && rm -rf /var/lib/apt/lists/*

# nikto from the official source (Perl), wrapped as /usr/local/bin/nikto.
RUN git clone --depth 1 https://github.com/sullo/nikto.git /opt/nikto \
    && printf '#!/bin/sh\nexec perl /opt/nikto/program/nikto.pl "$@"\n' > /usr/local/bin/nikto \
    && chmod +x /usr/local/bin/nikto

# ffuf: static Go binary from the official release (not packaged on bookworm).
RUN ARCH="$(dpkg --print-architecture)" \
    && case "$ARCH" in \
         amd64) F=linux_amd64 ;; \
         arm64) F=linux_arm64 ;; \
         *)     F=linux_amd64 ;; \
       esac \
    && wget -qO /tmp/ffuf.tar.gz \
        "https://github.com/ffuf/ffuf/releases/download/v2.1.0/ffuf_2.1.0_${F}.tar.gz" \
    && tar -xzf /tmp/ffuf.tar.gz -C /usr/local/bin ffuf \
    && rm -f /tmp/ffuf.tar.gz \
    && ffuf -V

# Wordlist where agent_runner.py's example commands expect it.
RUN mkdir -p /usr/share/wordlists \
    && cp /usr/share/dirb/wordlists/common.txt /usr/share/wordlists/common.txt

WORKDIR /work

# Keep the container alive so the harness can `docker exec` into it.
CMD ["sleep", "infinity"]
