#!/bin/sh
# Sobe o Monitor Fiscal neste host. Roda de dentro de /opt/Monitor-fiscal.
#
#   cd /opt/Monitor-fiscal && sh subir.sh
#
# Faz tudo: busca a chave, grava a senha, constroi, sobe e confere. Pode rodar
# de novo quantas vezes quiser -- so refaz o que falta.

set -e
cd "$(dirname "$0")"

ANTIGO=192.168.1.108
PORTA=8085

echo "== 1. a chave SSH dos PDVs =="
if [ -f monitorfiscal.key ]; then
  echo "   ja existe"
else
  # Vem DIRETO do servidor antigo para ca. Nao passa pelo compartilhamento de
  # rede de proposito: chave privada em \\servidor\opt fica legivel para quem
  # montar o compartilhamento.
  echo "   buscando de $ANTIGO (vai pedir a senha do root de la)"
  scp -o StrictHostKeyChecking=no root@$ANTIGO:/root/.ssh/monitorfiscal ./monitorfiscal.key
fi
chmod 600 monitorfiscal.key

echo "== 2. a senha de root dos PDVs =="
if [ -f .senha-pdv ] && [ -s .senha-pdv ]; then
  echo "   ja existe"
else
  printf "   senha de root dos PDVs (192.168.1.121-124): "
  stty -echo; read SENHA; stty echo; echo
  printf %s "$SENHA" > .senha-pdv
  unset SENHA
fi
chmod 600 .senha-pdv

echo "== 3. known_hosts =="
# Sem ele o coletor recusa as maquinas na primeira conexao. Ja vem junto, mas
# se faltar, o strict_host_key do config.json esta em "no" e ele se vira.
[ -f known_hosts ] || : > known_hosts

echo "== 4. rota ate os PDVs (informativo, nao impede de subir) =="
for h in 121 122 123 124; do
  printf "   192.168.1.%s " $h
  if timeout 4 sh -c "</dev/tcp/192.168.1.$h/22" 2>/dev/null; then
    echo "ok"
  else
    echo "SEM ROTA -- o painel vai mostrar este caixa em 'sem sinal'"
  fi
done

echo "== 5. construindo e subindo =="
docker compose up -d --build

echo "== 6. conferindo =="
# O healthcheck leva ate 20 s (start_period), entao esperar aqui e honesto.
sleep 12
echo -n "   /api/saude: "
curl -s --max-time 8 "http://127.0.0.1:$PORTA/api/saude" || echo "(sem resposta)"
echo
echo -n "   /api/estado sem token deve ser 401: HTTP "
curl -s -o /dev/null -w '%{http_code}\n' --max-time 8 "http://127.0.0.1:$PORTA/api/estado"

echo
echo "Painel: http://192.168.0.50:$PORTA"
echo "Se 'conectados' vier 0, o container subiu mas nao alcanca os PDVs --"
echo "veja o passo 4 acima. E rota entre as faixas, nao problema do container."
echo
echo "Log ao vivo:  docker compose logs -f"
