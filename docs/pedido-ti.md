# Monitor Fiscal — o que precisamos configurar nos self-checkouts

> Para: TI · De: Rodolfo Almeida · 02/09/2026
> Máquinas: **self-checkouts 221, 222, 223 e 224** — `192.168.1.121` a `.124`
> Projeto: painel de tablet que avisa o fiscal de loja quando um self-checkout
> entra em espera por autorização, e permite ajustar o volume da máquina à
> distância.

O app roda **dentro da rede**, num container Docker no servidor. Ele precisa de
duas coisas em cada self-checkout: **ler uma linha de log** e **ajustar o volume**.
Nada além disso.

---

## Parte 1 — Levantamento: ✅ FEITO em 02/09/2026 no SELF04 (`192.168.1.124`)

Não é preciso rodar nada. Estes são os retornos reais da máquina:

| O que | Resultado |
|---|---|
| Sistema | **Linux 6.12.5 x86_64**, Core i3-12100, host `SELF04.scastanha.com.br` |
| Log | `/var/venditor/log/display.log` — **existe e cresce** (≈5 MB/dia) |
| Permissão do log | `venditor:venditor` **666** — já legível por qualquer usuário |
| Rotação | **4 gerações** (`display.log.1.gz` … `.4.gz`), irregular |
| Áudio | `/usr/bin/amixer` e `/usr/sbin/alsactl` presentes |
| Mixer | **`Master` existe** — confirmado no `amixer scontrols` |

Duas consequências para o pedido abaixo:

- **A leitura do log não precisa de ajuste de permissão nenhum.** O arquivo já
  está `666`. O item 2.4 desta lista deixou de ser necessário.
- **O nome do mixer é `Master` mesmo.** O script da Parte 2 vai como está.

⚠️ **`alsamixer` não serve aqui.** Ele é uma tela interativa e não aceita
parâmetro; quem serve para automação é o **`amixer`**, que é o irmão de linha de
comando do mesmo pacote.

⚠️ **A máquina não é a imagem antiga do parque.** Kernel 6.12.5 de dezembro/2024,
64 bits — nada a ver com o Slackware 32 bits dos PDVs tradicionais. Nada do que
foi levantado nos caixas antigos pode ser assumido aqui.

Ainda falta confirmar **quem restaura o volume no boot** — o `alsactl store` do
script grava o estado, mas alguém precisa restaurá-lo na inicialização:

```sh
ls -l /var/lib/alsa/asound.state
systemctl status alsa-restore 2>/dev/null || ls -l /etc/rc.d/rc.alsa
```

---

## Parte 2 — Configuração (uma vez por máquina)

### 2.1 Um usuário dedicado, sem acesso a mais nada

Não queremos que o painel entre como `root`. Ele entra como um usuário que só
consegue executar um script e nada mais.

```sh
useradd -m -G audio -s /bin/sh monitorfiscal
```

O grupo `audio` é o que dá direito ao mixer. Confirmar com `groups monitorfiscal`.

### 2.2 O script — a única via de entrada

Salvar como `/usr/local/bin/mf-agente`, dono `root`, permissão `755`.

```sh
#!/bin/sh
# Unica via do Monitor Fiscal dentro do self-checkout.
# Aceita EXATAMENTE tres comandos. Qualquer outra coisa e recusada.
# Se o controle do mixer nao se chamar Master, trocar MIX abaixo.

MIX="Master"
MIN=30      # piso de volume: a maquina nunca fica muda por engano
MAX=100

ler() { amixer sget "$MIX" | grep -o '[0-9]*%' | head -n 1; }

case "$SSH_ORIGINAL_COMMAND" in

  volume-ler)
    ler
    ;;

  "volume-definir "*)
    V=`echo "$SSH_ORIGINAL_COMMAND" | sed 's/[^0-9]//g'`
    [ -z "$V" ] && exit 2
    [ "$V" -lt "$MIN" ] && V="$MIN"
    [ "$V" -gt "$MAX" ] && V="$MAX"
    amixer sset "$MIX" "$V%" > /dev/null 2>&1 || exit 3
    alsactl store > /dev/null 2>&1        # para sobreviver ao reboot
    ler                                    # devolve o volume REAL, nao o pedido
    ;;

  log-seguir)
    exec tail -n 0 -F /var/venditor/log/display.log
    ;;

  *)
    echo "comando nao permitido" >&2
    exit 1
    ;;
esac
```

Três detalhes que não são estilo:

- **O piso de 30%.** Sem ele, alguém zera o volume sem querer e o self-checkout
  fica mudo — e ninguém descobre por quê. Ajustável, mas não deve ser zero.
- **O `volume-definir` termina lendo de volta.** O painel mostra o volume que a
  máquina respondeu, não o que o controle deslizante mandou. Comando aceito não
  é comando aplicado.
- **O `alsactl store`.** Sem ele o ajuste se perde na primeira queda de energia.
  Se o item 4 do levantamento mostrar que a máquina não restaura no boot, isso
  precisa ser resolvido junto.

### 2.3 A chave SSH, restrita ao script

Geramos a chave do nosso lado e enviamos só a pública. No self-checkout:

```sh
mkdir -p /home/monitorfiscal/.ssh
# colar a linha abaixo em /home/monitorfiscal/.ssh/authorized_keys,
# substituindo AAAA... pela chave publica que enviarmos:
# command="/usr/local/bin/mf-agente",no-port-forwarding,no-X11-forwarding,no-agent-forwarding,no-pty ssh-ed25519 AAAA... monitor-fiscal

chmod 700 /home/monitorfiscal/.ssh
chmod 600 /home/monitorfiscal/.ssh/authorized_keys
chown -R monitorfiscal /home/monitorfiscal/.ssh
```

O `command=` é o que fecha a porta: mesmo que a chave vaze, ela **só** executa o
`mf-agente`. Não abre shell, não abre túnel, não roda outra coisa.

### 2.4 Permissão de leitura do log — ~~pendente~~ não é necessária

O arquivo já está `666` (`venditor:venditor`). Qualquer usuário lê. Nada a fazer.

> Observação, não pedido: `666` em log é permissivo — qualquer usuário da máquina
> também **escreve** nele. Não afeta este projeto, mas vale a TI saber.

### 2.5 Rede

O container no servidor precisa alcançar a **porta 22** dos quatro
self-checkouts. Já conferimos daqui: as quatro respondem (`.121` a `.124`).
Se houver regra de firewall por origem, liberar o IP do host do Docker.

---

## Parte 3 — O repositório

O código fica num **repositório Git próprio**, e o TI clona para um container
interno no servidor. Ainda a definir: conta/organização e nome do repositório.

---

## O que NÃO estamos pedindo

Para não haver dúvida sobre o alcance:

- Não pedimos acesso `root` contínuo, nem shell para o app.
- Não pedimos nada que altere a aplicação de PDV, o venditor ou a configuração
  fiscal.
- Não vamos gravar em nenhum arquivo da máquina além do estado do mixer
  (`alsactl store`).
- O painel **não** lê o texto do visor — só o campo de estado. O log contém nome
  de operador, matrícula e valor de compra do cliente, e nada disso sai da
  máquina.
