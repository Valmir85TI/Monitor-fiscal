# Monitor Fiscal — coletor + API + painel.
# Roda na rede interna. Não expor para a internet.
FROM python:3.12-alpine

# openssh-client  o coletor mantém um `tail -F` por máquina, via SSH.
# expect          o acao-pdv.exp entra nos PDVs por senha para destravar,
#                 reiniciar e mexer no volume. Sem ele, a tela ⚙ não funciona
#                 e o erro aparece só quando alguém aperta um botão.
# tzdata          os horários do painel são de loja, não UTC.
RUN apk add --no-cache openssh-client expect tzdata
ENV TZ=America/Sao_Paulo

WORKDIR /app
COPY coletor/     /app/coletor/
COPY web/         /app/web/
COPY acao-pdv.exp /app/acao-pdv.exp
RUN chmod 700 /app/acao-pdv.exp

# Config, chave e senha entram por volume — ver docker-compose.yml.
ENV MF_CONFIG=/app/config.json

# A chave SSH precisa de permissão fechada, senão o cliente recusa usá-la.
# O volume entra como :ro, então a cópia é feita na subida, não no build.
# `exec` no fim para o python virar PID 1 e receber o SIGTERM do `docker stop`
# sem esperar os 10 s de timeout.
ENTRYPOINT ["/bin/sh", "-c", "\
  mkdir -p /root/.ssh && \
  cp /run/secrets/monitorfiscal /root/.ssh/monitorfiscal && \
  chmod 600 /root/.ssh/monitorfiscal && \
  cp /app/known_hosts /root/.ssh/known_hosts 2>/dev/null || true; \
  exec python3 -u /app/coletor/monitor.py"]

EXPOSE 8080
