# Levantamento do self-checkout — SELF04 (`192.168.1.124`)

Medido em **02/09/2026**, leitura direta na máquina. Tudo aqui é observação, não
suposição — e o que ainda é suposição está marcado.

## A máquina não é a imagem antiga do parque

```
Linux SELF04.scastanha.com.br 6.12.5 #1 SMP PREEMPT_DYNAMIC
Sat Dec 14 17:50:35 CST 2024  x86_64  12th Gen Intel Core i3-12100
```

Kernel de dezembro de 2024, 64 bits, i3 de 12ª geração. **Nada a ver** com o
Slackware 32 bits de 2016 dos PDVs tradicionais. Toda conclusão tirada do PDV 208
precisa ser reconfirmada aqui antes de virar premissa.

## O log

`/var/venditor/log/display.log` — `venditor:venditor`, permissão `666`,
≈ **5 MB/dia**. Vizinhos no mesmo diretório: `venditor.log` (29 MB),
`ft001_scanner.log`, `ftself.log`, `prunepos.log`.

**Rotação: 4 gerações**, irregular (`.1` de 01/09, `.2` e `.3` de 31/08, `.4` de
28/08). 🔴 **Não são as 61 gerações do PDV tradicional** — o histórico disponível
é de ~4 a 5 dias, não dois meses.

### 🔴 Ele escreve TODO SEGUNDO, mesmo parado

```
---------------------------------------- SCREENSV(22) 0/0 1 02/09/26 16:28:21 193
Proximo Cliente
---------------------------------------- SCREENSV(22) 0/0 1 02/09/26 16:28:22 193
Proximo Cliente
---------------------------------------- SCREENSV(22) 0/0 1 02/09/26 16:28:23 193
Proximo Cliente
```

Esta é a diferença mais importante entre o self-checkout e o caixa tradicional, e
ela inverte uma regra do projeto:

| | PDV tradicional (208) | Self-checkout (SELF04) |
|---|---|---|
| Escrita | só quando o visor **muda** | **1 bloco por segundo**, sempre |
| Silêncio no arquivo | operador ocioso — **não é falha** | **é falha** |
| Medir espera | precisa **parear** início e fim | **conta segundos direto** |

Duas consequências boas:

1. **"Sem sinal" fica honesto e barato.** No 208 a idade do arquivo media
   inatividade do operador; aqui ela mede o processo. O arquivo parou = a máquina
   ou o venditor pararam.
2. 🟢 **O problema que travava o baseline não existe aqui.** No 208 só 9 a 92 dos
   62 a 220 chamados diários fechavam par com a autorização, e por isso a espera
   era piso, não retrato. Como o self grava a cada segundo, a duração do episódio
   é **contagem direta**.

⚠️ Em troca, `mudou_em` não pode mais vir da data de modificação do arquivo: como
o conteúdo se repete, "última mudança" tem de ser calculada comparando o bloco com
o anterior.

## O vocabulário de estado é OUTRO — e mais rico

Contagem de blocos por estado no arquivo do dia (30.656 blocos, até 16:28):

| Estado | Blocos | Leitura |
|---|---:|---|
| `SCREENSV(22)` | 29.135 | protetor de tela, "Próximo Cliente" — máquina ociosa |
| `SALE(1)` | 394 | item sendo registrado |
| `IDLE(4)` | 329 | aguardando |
| `EFTPAY(67)` | 201 | pagamento em cartão |
| `extra(74)` | 184 | ⚠️ não identificado |
| `HELLO(19)` | 138 | abertura de atendimento |
| `SUBTOTAL(2)` | 104 | subtotal no visor |
| **`AUTH(68)`** | **53** | **chamado/autorização de fiscal** |
| `Z(7)` | 36 | Redução Z / fora de operação |
| `extra(31)` | 31 | ⚠️ não identificado |
| `PUT_ITEM(65)` | 26 | pedindo para colocar o item na balança |
| `REMBAG(64)` | 11 | pedindo para retirar da sacola |
| `SUB_MSGS(30)` | 10 | ⚠️ não identificado |
| `PUTBACK(69)` | 4 | pedindo para devolver o item |

O estado agora vem com **código numérico** entre parênteses — mais estável para
código do que casar a palavra.

`PUT_ITEM`, `REMBAG` e `PUTBACK` são exatamente as intervenções de divergência de
peso, que são a razão de o fiscal ser chamado num self-checkout. Elas não existem
no caixa tradicional.

### `AUTH(68)` é o chamado de fiscal

O subcódigo `5/0` traz no visor:

```
Menu de Funcoes
Fiscal?
```

🔴 **Mas `AUTH(68)` também aparece na abertura do caixa**, com "Caixa Fechado" no
visor, às 08:01. Nem todo `AUTH` é cliente esperando. Separar o ritual de abertura
do chamado real é tarefa aberta.

## Primeira contagem — ainda NÃO é baseline

Episódios de `AUTH` no dia, até 16:28, agrupando segundos consecutivos:

```
3 s · 3 s · 4 s · 12 s · 4 s · 3 s · 3 s · 7 s
8 episódios · 39 segundos no total · pior caso 12 s
```

🔴 **Não use este número como baseline.** Três motivos:

1. **A máquina passou o dia praticamente parada** — 29.135 dos 30.656 blocos são
   protetor de tela, ou seja ~8 h de ociosidade. Foi escolhida justamente por ter
   pouco movimento.
2. **Parte desses `AUTH` é a abertura das 08:01**, não cliente na fila.
3. **Um dia, uma máquina.** O baseline precisa das quatro, em dias de movimento.

O que este número prova é outra coisa, e é o que importa agora: **o método
funciona**. Dá para contar episódios e medir a duração de cada um direto do log,
sem parear nada.

## Áudio

`amixer` e `alsactl` presentes; o controle **`Master` existe**. Outros controles
disponíveis: `Headphone`, `PCM`, `Front`, `Surround`, `Center`, `LFE`, `Line`,
`IEC958`.

🔴 Falta confirmar quem restaura o volume no boot.

---

# 🔴 A medição das QUATRO máquinas — e ela contraria a premissa do projeto

Medido em 02/09 nos quatro self-checkouts (SELF01 a SELF04, `.121` a `.124`),
sobre todo o histórico disponível: **25/08 a 02/09, 5 dias úteis de dado**.

## Episódios de autorização de fiscal

**756 episódios.** Média **2,7 s**. Pior caso **13 s**.
**Zero episódios acima de 30 s. Zero acima de 60 s.**

O pior dia de todos foi o SELF01 em 01/09: 118 episódios, 339 segundos somados —
5 minutos e meio de fiscal na tela **no dia inteiro**.

## Não é artefato da definição — nenhum estado segura

A primeira suspeita foi de que eu estivesse medindo a operação do fiscal, e não a
espera do cliente. Para descartar, medi quanto tempo a máquina fica parada em
**cada** estado, nas quatro máquinas, em todo o histórico:

| Estado | Paradas | Média | Pior | Acima de 30 s |
|---|---:|---:|---:|---:|
| `IDLE(4)` | 2.206 | 4,9 s | 35 s | 56 |
| `EFTPAY(67)` | 1.376 | 5,5 s | 117 s | 14 |
| `SALE(1)` | 3.970 | 3,4 s | **17 s** | 0 |
| `AUTH(68)` | 826 | 3,8 s | **12 s** | 0 |
| `PUT_ITEM(65)` | 2.222 | 1,2 s | **6 s** | 0 |
| `REMBAG(64)` | 598 | 1,0 s | **7 s** | 0 |
| `SUBTOTAL(2)` | 1.351 | 1,6 s | **8 s** | 0 |

As únicas corridas longas são `SCREENSV` (protetor de tela) e `CLOSED` — máquina
ociosa ou fechada, o que é normal.

**Como o log grava um bloco por segundo, uma tela travada apareceria como corrida
longa.** Nenhum estado transacional passa de 35 s em cinco dias e quatro máquinas.

## O que isso significa

🔴 **A dor que abriu este projeto não está nos self-checkouts.** Os 62 a 220
chamados por dia e a cauda de 141, 323, 351 e 359 segundos foram medidos no **PDV
208, caixa tradicional com operadora**. Nos selfs, a autorização acontece em ~3
segundos — compatível com um fiscal que já está de pé na ilha, ao lado das
máquinas, e não atravessando a loja.

Duas leituras cabem, e elas levam a lugares diferentes:

1. **O fiscal já cobre bem a ilha de autoatendimento.** Aí não há ganho a capturar
   aqui, e o painel deve voltar a mirar os caixas tradicionais, onde a cauda de
   6 minutos foi de fato medida.
2. **A espera acontece fora do log** — o cliente desiste, vira e procura o fiscal
   antes de a tela mudar. Nesse caso o `display.log` não vê o problema, e nenhuma
   quantidade de engenharia em cima dele vai ver.

**A segunda hipótese custa uma hora de observação na ilha para ser descartada.
A primeira custa reescrever o alvo do projeto.** Qualquer uma das duas é mais
barata agora do que depois de o painel existir.

## Observação lateral, possivelmente mais valiosa

O SELF04 passou 29.135 dos 30.656 blocos do dia em protetor de tela — **95% do
tempo ocioso**. O padrão se repete nas outras três. Se as quatro máquinas de
autoatendimento estão paradas quase o dia inteiro, a pergunta de negócio deixa de
ser "o fiscal chega rápido?" e passa a ser **"por que ninguém usa o
autoatendimento?"** — que é um problema maior e de outro dono.

---

## O que fica aberto

1. Rodar a mesma contagem nas quatro máquinas, nos 4–5 dias de histórico que
   existem, e passar a arquivar a partir de agora — a rotação curta apaga o resto.
2. Identificar `extra(74)`, `extra(31)` e `SUB_MSGS(30)`.
3. Separar `AUTH` de abertura de `AUTH` de cliente esperando.
4. Confirmar se as outras três máquinas têm a mesma imagem e o mesmo vocabulário.
5. Trocar a senha de `root` por chave: hoje o acesso é senha compartilhada.
