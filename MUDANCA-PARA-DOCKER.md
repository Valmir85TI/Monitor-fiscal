# Mudança do 192.168.1.108 para o Docker do 192.168.0.50

O projeto inteiro já está em `/opt/Monitor-fiscal`. Falta rodar **um comando** no
host — o `subir.sh` cuida do resto, inclusive dos dois segredos.

---

## 1. Subir — um comando

```sh
cd /opt/Monitor-fiscal && sh subir.sh
```

Ele busca a chave SSH direto do `192.168.1.108` (pede a senha de lá), pergunta a
senha de root dos PDVs, testa a rota, constrói e sobe. Pode rodar de novo
quantas vezes quiser — só refaz o que falta.

**A chave SSH e o `.senha-pdv` JÁ ESTÃO na pasta** (copiados a pedido do
Valmir em 11/09). O `subir.sh` vê que existem e pula a etapa — só ajusta a
permissão para 600, que é o que o cliente SSH exige.

⚠️ Fica registrado o que isso significa: `monitorfiscal.key` dá **root nos
quatro PDVs**, e está num compartilhamento de rede — qualquer um que monte
`\\192.168.0.50\opt` consegue ler. Se um dia quiser fechar isso, apague os dois
da pasta e rode o `subir.sh` de novo: ele busca a chave direto do
`192.168.1.108` e pergunta a senha, sem nada passar pelo compartilhamento.

---

## 2. A rota até os PDVs

O container precisa alcançar `192.168.1.121` a `.124`, e ele vive em
`192.168.0.50` — outra faixa. O `subir.sh` testa e **avisa, mas não impede**.

Sem rota, o painel sobe e mostra os quatro caixas em **"sem sinal"**, com o
motivo na célula. É o comportamento desenhado: máquina que não fala nunca some
da tela e nunca fica verde. Resolvida a rota, os caixas acendem sozinhos, sem
mexer em nada.

O container sai pelo NAT do host: se o host não chega, o container também não.
Então o teste vale rodar do próprio host:

```sh
for h in 121 122 123 124; do
  printf "192.168.1.$h -> "
  timeout 5 bash -c "</dev/tcp/192.168.1.$h/22" 2>/dev/null && echo ok || echo SEM ROTA
done
```

---

## 3. Conferir

```sh
curl -s http://192.168.0.50:8085/api/saude
# {"ok": true, "caixas": 4, "conectados": 4}
```

`conectados: 4` é o que importa. `0` = subiu, mas não alcança os PDVs.

---

## 4. O endereço do tablet muda

| | |
|---|---|
| antes | `http://192.168.1.108:8080` |
| agora | `http://192.168.0.50:8085` |

**8080 é do Apache** nesse host. Sondei o host e estão ocupadas: 80, 82, 3000,
4200, 8000, 8080, 8081, 8083, 8084, 8086, 8087, 8090, 8091, 8095, 8098. A 8085
respondeu livre e não é reivindicada por nenhum compose de `/opt`.

O PIN continua o mesmo (`pin_acoes` no `config.json`).

---

## 5. Desligar o antigo — só depois

Deixe o `192.168.1.108` rodando até o novo passar um dia inteiro de loja. Os
dois no ar ao mesmo tempo não se atrapalham: ambos só **leem** o log dos PDVs,
e cada `tail -F` é uma sessão independente.

O que **não** pode é os dois com o botão de ação em uso, porque `reboot` e
`pkill vend` mexem na máquina de verdade. Na prática, use a tela ⚙ de um só.

Quando decidir desligar:

```sh
ssh root@192.168.1.108 "pkill -f 'coletor/monitor.py'"
```

E tire o `iniciar.sh` do boot, se estiver no `rc.local`.

---

## O que mudou no código para caber no container

- **`/api/saude`**, sem sessão, para o healthcheck. O antigo batia em
  `/api/estado`, que responde 401 desde que o painel ganhou PIN — o container
  ficaria `unhealthy` para sempre e o compose o reiniciaria em círculo.
  O endpoint devolve só contagem: `{"caixas": 4, "conectados": 4}`. Nunca
  estado de caixa nem cesta — endpoint aberto não pode virar a porta dos fundos
  que a tranca fechou na frente.
- **`MF_SENHA`** no `acao-pdv.exp`: o caminho da senha era fixo em
  `/root/monitor-fiscal/.senha-pdv`. Agora vem do ambiente, com esse mesmo
  caminho como padrão — então a instalação do `192.168.1.108` continua
  funcionando sem alteração nenhuma.
- **`expect` no Dockerfile.** O `docker/Dockerfile` antigo instalava só
  `openssh-client`, porque foi escrito antes da tela de ações existir. Sem
  `expect`, o painel sobe e parece bem, e o erro só aparece quando alguém
  aperta um botão.
- **Limite de log** no compose. O disco do host é compartilhado com todos os
  outros projetos de `/opt`; sem limite, um serviço que fica meses no ar enche
  o disco de todo mundo.

O `docker/` antigo do projeto ficou para trás: apontava para `../config.json`
numa árvore que não existe mais nesta pasta plana, e trazia o healthcheck que
hoje daria 401.
