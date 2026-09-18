# Monitor Fiscal do PDV

- **Squad:** tecnologia
- **Aberto em:** 02/09/2026
- **Dor:** o **fiscal de loja** (a pessoa) só descobre que um caixa precisa dela quando a
  operadora levanta a mão, grita ou chama no rádio. Enquanto isso o **cliente fica parado
  com a compra em cima da esteira**. Quem sente: o cliente na fila, a operadora travada
  sem autorização, e o fiscal, que hoje patrulha às cegas.
- **Como é hoje:** chamado verbal. **Ninguém mede** — não existe registro de quantas vezes
  o fiscal foi chamado, nem de quanto o cliente esperou.
- **Unidade do ganho:** ⏱ **segundos de cliente parado por chamado** (principal) e, em
  segundo plano, horas do fiscal que hoje se vão em ronda sem alvo.
- **Audiência do resultado:** Diretoria + TI · **reportar em:** 02/10/2026

## Baseline (medido em 02/09/2026)

🟢 **Medido, não estimado** — e essa é a parte incomum deste contrato: o baseline saiu do
histórico que já existia. O `/var/log/display.log` do venditor guarda **61 dias** de
rotação, e os dias de julho/agosto do PDV 208 são operação real. Ver
`memory/ref_display_log_estado_do_caixa.md`.

Sete dias reais, **um único caixa**:

| Dia | Chamados de fiscal | Pareados | Espera média | Pior caso | Acima de 30 s |
|---|---:|---:|---:|---:|---:|
| 12/08 | 62 | 14 | 3,1 s | 12 s | 0 |
| 08/08 | 112 | 16 | 11,2 s | 67 s | 1 |
| 07/08 | 74 | 10 | 39,9 s | **359 s** | 1 |
| 05/08 | 98 | 15 | 31,1 s | **351 s** | 2 |
| 03/08 | 72 | 9 | 20,3 s | 141 s | 1 |
| 31/07 | 220 | 92 | 8,8 s | **323 s** | 3 |
| 29/07 | 124 | 11 | 6,8 s | 17 s | 0 |

**Origem do número:** contagem direta sobre `display.log.N.gz` do PDV 208, deduplicada por
episódio (uma tela repetida não conta duas vezes). Um chamado começa quando o visor passa a
pedir `SOLICITE A SENHA` / `Fiscal?`; termina quando aparece `Fiscal <matrícula>`, que é a
autorização acontecendo.

### 🔴 O limite honesto deste baseline

**Só 9 a 92 dos 62 a 220 chamados por dia foram pareados** com uma autorização. O resto não
fechou o par: o chamado pode ter sido resolvido de outro jeito, cancelado, ou o meu
pareamento não pegou. Portanto:

- **"62 a 220 chamados/dia por caixa" é firme** — é contagem de episódio.
- **A espera é piso, não retrato.** As médias vêm de uma fatia pequena, e a cauda
  (141 s, 323 s, 351 s, 359 s) é o que interessa, não a média.
- **Fechar o pareamento é a primeira tarefa do projeto**, antes de qualquer tela. Sem isso
  o ganho não é demonstrável — e a régua do "depois" tem de ser a mesma do "antes".

### Ordem de grandeza (extrapolação, não medição)

Se a loja tem 13 caixas e cada um repete 1 a 3 chamados/dia acima de 30 s, são ~13 a 40
episódios/dia de cliente visivelmente parado. **Isto é extrapolação de um caixa para o
parque**, com a hipótese não verificada de que os caixas se parecem. Não usar em informe
sem medir pelo menos três máquinas de perfis diferentes.

⚠️ **Não converter para R$** sem o Rodolfo dar a régua. Não existe valor-hora de cliente em
fila neste repositório, e inventar um destruiria a credibilidade do informe.

## Meta

Que o fiscal **chegue antes de ser chamado**: o tablet avisa no instante em que o caixa
entra em estado de espera por autorização. Alvo: **nenhum episódio acima de 60 s** e
derrubar o pior caso do dia dos ~6 min de hoje.

## O que é (e o que não é)

O Rodolfo definiu a fronteira: **é o zoom num caixa.** O Pulso e o Painel de PDV olham o
**parque** e servem para *achar* o problema; este mergulha em **um caixa**, ao vivo, e serve
para *atender*. Não competem e não se fundem.

| | Pulso | Painel de PDV | **Monitor Fiscal** |
|---|---|---|---|
| Olha | parque (13 cards) | parque (venda/cupom) | **um caixa** |
| Fonte | agente Zabbix | ERP Bluesoft | **`display.log` na máquina** |
| Para quem | TI | Rodolfo + TI | **fiscal de loja, no tablet** |
| Pergunta | "a máquina está de pé?" | "esse caixa vende fora do padrão?" | **"preciso ir até lá agora?"** |

## As telas

Confirmadas pelo Rodolfo: **estado do caixa ao vivo** e **alertas abertos**.

🔴 **"4 telas divididas" ainda está ambíguo** e é a primeira decisão da próxima sessão. Duas
leituras cabem no que foi dito:

1. **4 painéis sobre o mesmo caixa** — estado, alertas, e mais dois a definir
   (candidatos: periféricos/impressora, documento fiscal).
2. **4 caixas ao mesmo tempo** — o fiscal cobre vários caixas, e "escolher qual PDV" seria
   escolher quais entram nos quadrantes.

A frase *"a pessoa escolhe qual PDV quer monitorar"* puxa para (1); *"fiscal da loja ficará
com o tablet em mãos para receber alertas"* puxa para (2), porque quem espera alerta não
fica olhando um caixa só. **Perguntar antes de desenhar.**

## Restrições que já nascem com o projeto

1. 🔴 **O `display.log` tem dado pessoal.** Traz `Fiscal <matrícula> <NOME COMPLETO>`, além
   de nome de produto e valor de compra do cliente. **Só o campo de ESTADO pode ir para a
   tela.** O texto do visor, não. Isso não é preferência de design: é base legal.
2. 🔴 **É ISO-8859-1**, não UTF-8. Transcodificar ou vira mojibake.
3. 🔴 **Silêncio no log não é falha.** O arquivo só cresce quando o visor muda; caixa ocioso
   não escreve. Idade do arquivo mede inatividade do operador, **não** morte do processo.
4. **A fonte é artefato de fornecedor.** O `--display_log` é padrão do `xvenditor.sh` dentro
   do pacote `venditor-2.9.1AD_x86` da Conecto — vale para o parque, mas pode mudar em
   qualquer atualização. O projeto tem de degradar com aviso, nunca em silêncio.
5. **Como o dado sai do PDV ainda não foi decidido.** O Pulso já tem agente Zabbix em cima
   da máquina; reaproveitar é o caminho óbvio, mas não foi medido se `log[]` do agente 2.4.3
   do parque dá conta. Decidir antes de construir.

## Resultado (preencher na entrega)
