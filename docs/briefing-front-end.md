# Monitor Fiscal do PDV — briefing de front-end

> **Para que serve este arquivo:** é o briefing visual do tablet do fiscal de loja,
> escrito para ser colado no **Google Stitch / AI Studio** e virar maquete.
> Contrato de valor: `docs/projetos/2026-09-02-monitor-fiscal-pdv.md`.
> Squad: tecnologia · Escrito em 02/09/2026.

⚠️ **Antes de colar em qualquer ferramenta do Google:** este documento não contém IP,
credencial, matrícula nem nome de funcionário — e não pode passar a conter. Os números
de PDV e os tempos que aparecem aqui são **exemplo de maquete**, não medição.

---

## 1. A pergunta que a tela responde

Uma só: **"preciso ir até lá agora?"**

Quem lê é o **fiscal de loja** — a pessoa que autoriza operações no caixa — andando pela
loja com um tablet na mão. Hoje ela só descobre que precisa quando a operadora levanta a
mão, grita ou chama no rádio; enquanto isso o cliente fica parado com a compra na esteira.

Isso **não** é um painel de análise. Não tem gráfico, não tem histórico, não tem KPI, não
tem filtro de período. Se um elemento não ajuda a decidir *ir ou não ir agora*, ele não
entra.

## 2. Contexto físico de uso (isto define o desenho todo)

| | |
|---|---|
| Aparelho | Tablet ~10", **paisagem**, 1280×800 |
| Postura | **Em pé, andando**, uma mão só, tablet a ~50 cm |
| Luz | Loja de supermercado — luz forte, reflexo na tela |
| Atenção | **Nenhuma.** A pessoa está atendendo outra coisa quando o alerta chega |
| Duração do olhar | **Menos de 1 segundo.** É glance, não leitura |

Consequência prática: o estado tem de ser legível **a 1,5 m de distância**, tipografia
grande, cor de alto contraste, e **som + vibração** carregam o alerta — a tela sozinha não
avisa ninguém que não está olhando.

## 3. Regras invioláveis

Estas não são preferência estética. Quebrar qualquer uma invalida a tela.

1. 🔴 **Só o campo de ESTADO vai para a tela.** A fonte (`display.log` do terminal) traz
   nome completo do operador, matrícula, nome de produto e valor da compra do cliente.
   **Nada disso pode ser renderizado, nunca**, nem em tooltip, nem em "detalhe". É base
   legal, não capricho. A tela mostra: número do PDV, estado, tempo. Só.
2. 🔴 **Ausência de dado tem cor própria e nunca se parece com "tudo certo".** Um painel
   cego que aparenta calma é pior que painel nenhum. Ver modo *Sem sinal* na §5.
3. 🔴 **Não existe botão "resolvido" / "atendido".** O episódio fecha sozinho quando a
   autorização acontece no caixa. Passo manual em processo de rotina não acontece — foi
   medido em outro projeto da casa e custou seis dias parados. Se a tela pedir um toque
   para limpar, o painel vira um campo de alertas velhos em uma semana.
4. 🔴 **Nenhum número inventado.** Ver §10 — vale especialmente para o Stitch.
5. **Cor nunca sozinha.** Toda cor vem acompanhada de palavra. Reflexo de loja e daltonismo
   matam painel que só fala por cor.

## 4. Tela A — Grid dos 4 caixas (tela principal, 95% do tempo)

```
┌────────────────────────────────────────────────────────────────┐
│ Monitor Fiscal · Castanha OS      14:31   atualizado há 2 s 🔊⚙ │  56 px
├───────────────────────────────┬────────────────────────────────┤
│                               │                                │
│   201                         │   203                          │
│   SUBTOTAL                    │   IDLE                          │
│   há 12 s                     │   há 1 min                     │
│                               │                                │
├───────────────────────────────┼────────────────────────────────┤
│ ███████████████████████████   │                                │
│ █  205    PRECISA DE VOCÊ █   │   208                          │
│ █                         █   │   FECHADO                      │
│ █        1 min 52         █   │   —                            │
│ ███████████████████████████   │                                │
├───────────────────────────────┴────────────────────────────────┤
│ ⚠ Fora da sua tela: 209 chamando há 34 s                       │  48 px
└────────────────────────────────────────────────────────────────┘
```

**Grid 2×2, posições FIXAS.** O quadrante em alerta **não** se move nem reordena. Com
quatro células, memória espacial ("o 205 é embaixo à esquerda") vale mais que ordenação —
reordenar obriga a reler a tela toda a cada alerta. Ordenação só compensa em lista longa.

**Cabeçalho (56 px):** título, relógio, **"atualizado há X s"** (frescor sempre visível,
nunca escondido), botão de som liga/desliga, engrenagem → Tela B.

**Rodapé (48 px) — 🔴 decisão pendente do Rodolfo.** O fiscal vê 4 dos 13 caixas. Se um
dos outros 9 chamar, o painel fica calmo mentindo. A proposta é esta faixa: uma linha só,
citando qualquer caixa fora dos quatro que esteja chamando, sem tirar o grid do lugar.
As alternativas são (a) aceitar que o fiscal cobre uma zona de 4 caixas e o resto é de
outra pessoa, ou (b) o grid mostrar sempre os 4 mais urgentes do momento — o que reintroduz
a movimentação que a posição fixa evita. **Se não houver rodapé, a tela precisa dizer em
algum lugar que ela cobre 4 de 13**, senão promete cobertura que não tem.

## 5. Anatomia do quadrante — seis modos

Cada célula tem exatamente um destes modos. O que muda entre eles é **fundo, cor e tamanho
do cronômetro** — a estrutura fica no lugar.

### 5.1 Tranquilo — o caixa está operando
Fundo papel `#FBF8F4`, borda fina `#E7E0D6`, filete verde de 4 px no topo (sinal de "vivo").
Número do PDV **56 px** semibold em Castanho Noite. Estado **26 px** maiúsculo, Cinza Quente.
Tempo no estado **18 px**, discreto. **Sem alarme, sem cor forte.**
Estados aqui: `SUBTOTAL`, `SALE`, `IDLE`, `QUERY`, `THANKYOU`, `BUSY`.

### 5.2 Chamando — recente (0 a 15 s)
Fundo âmbar fraco `#FDF3E2`, borda `#B26A00`. Aparece a frase **"PRECISA DE VOCÊ"** em
**34 px** bold. O **cronômetro assume o centro**: `88 px`, tabular, contando de segundo em
segundo. Um bipe curto, uma vez.

### 5.3 Chamando — atenção (15 a 60 s)
Fundo vermelho fraco `#FCECEA`, borda e cronômetro em `#C0261F`. Cronômetro `96 px`.
Bipe curto repetido a cada 15 s.

### 5.4 Crítico — acima de 60 s (meta do projeto violada)
**Quadrante inteiro vermelho `#C0261F`, texto branco.** Cronômetro `120 px`. Respiração
lenta de opacidade (1,4 s, suave — não pisca rápido, que cansa e é rejeitado por quem tem
sensibilidade a movimento; respeitar `prefers-reduced-motion` removendo a animação e
mantendo a cor). Som repetido + **vibração**.
> O limiar de 60 s é a meta escrita no contrato: nenhum episódio acima de 60 s. Hoje o pior
> caso medido passa de 5 minutos.

### 5.5 Fora de operação — `CLOSED` e `Z`
Cinza mudo `#F2EEE8`, texto `#9A9086`, rótulo **"FECHADO"** ou **"REDUÇÃO Z"**, sem
cronômetro grande. **Não é problema e não pode parecer problema.**

### 5.6 🔴 Sem sinal — o coletor parou de falar
Fundo cinza com hachura diagonal, faixa preta e branca no topo, texto **"SEM SINAL há
2 min"**. Visualmente distinto tanto de "tudo certo" quanto de "alarme": é a tela admitindo
que está cega naquele caixa.

**Por que este modo é obrigatório e como ele se distingue de caixa parado:** o arquivo de
origem só cresce quando o visor do caixa muda — **caixa ocioso não escreve nada**. Logo,
"faz tempo que não muda" é operador sem cliente, não falha. A tela precisa de **dois
relógios distintos**, e o back-end tem de mandar os dois:
- `mudou_em` — última mudança de visor → alimenta o "há 12 s" do §5.1.
- `visto_em` — último batimento do coletor dizendo *"li o arquivo, e nada mudou"* → é este,
  e só este, que dispara *Sem sinal*.

Confundir os dois transforma caixa vazio às 9h da manhã em alarme, e o painel é desligado na
primeira semana.

## 6. Vocabulário de estado — é fechado, oito palavras

Medido em operação real. **Não inventar estado novo.** A coluna "rótulo" é o texto exato
que vai na tela.

| Estado na fonte | Rótulo na tela | Modo |
|---|---|---|
| `SUBTOTAL` | SUBTOTAL | tranquilo |
| `SALE` | REGISTRANDO | tranquilo |
| `IDLE` | LIVRE | tranquilo |
| `THANKYOU` | FINALIZADA | tranquilo |
| `BUSY` | PROCESSANDO | tranquilo |
| `QUERY` | CONSULTA DE PREÇO | tranquilo |
| `CLOSED` | FECHADO | fora de operação |
| `Z` | REDUÇÃO Z | fora de operação |

O **chamado de fiscal** não é um nono estado: é uma condição que se sobrepõe ao estado
corrente (o caixa continua em `SUBTOTAL` enquanto espera a senha). Na tela, o modo de
alerta **substitui** a aparência tranquila, e o rótulo de estado continua visível em corpo
menor.

## 7. Tela B — Escolher os caixas

Abre pela engrenagem. Lista os caixas da loja, o fiscal marca **até 4**, e a ordem em que
marcou define a posição no grid (1 = superior esquerdo, sentido horário). Fica salvo no
aparelho — não se pergunta de novo a cada abertura.

Cada linha: número do PDV grande, estado atual em corpo pequeno, caixa de seleção grande o
bastante para dedo (alvo mínimo 48 px). Botão **"Usar estes 4"** fixo no rodapé.
Sem busca, sem filtro: é uma lista de treze itens.

## 8. Tela C — variante em avaliação (gerar como alternativa, não como principal)

Quando **um** caixa passa de 60 s, o tablet abandona o grid e mostra só ele, em tela cheia:
número do PDV gigante, cronômetro, nada mais. A favor: a essa altura só existe uma coisa a
fazer, e o grid vira ruído. Contra: se dois caixas estourarem juntos, o takeover esconde um
deles — e a regra §3.2 diz que a tela não pode esconder.

**Gerar as duas e decidir olhando.** Se for adotada, a regra é: takeover só com exatamente
um crítico; havendo dois, volta ao grid.

## 9. Paleta e tipografia

**Fonte: Poppins** (fonte principal da marca), pesos 400/600/700. Números de cronômetro em
**tabular-nums** — sem isso o número treme a cada segundo e chama atenção à toa.

| Papel | Hex | Uso |
|---|---|---|
| Vermelho Castanha | `#CC1F1F` | barra do cabeçalho |
| Castanho Noite | `#1A1008` | texto principal |
| Cinza Quente | `#3D3328` | texto secundário |
| Papel | `#FBF8F4` | fundo da tela |
| Linha | `#E7E0D6` | bordas |
| Operando | `#1F7A4D` / `#E8F5EE` | filete "vivo" |
| Chamando | `#B26A00` / `#FDF3E2` | modo 5.2 |
| Crítico | `#C0261F` / `#FCECEA` | modos 5.3 e 5.4 |
| Mudo | `#9A9086` / `#F2EEE8` | fora de operação, sem sinal |

⚠️ **O manual da marca não tem verde nem âmbar** — a paleta oficial é vermelho e neutros.
O desvio é deliberado e igual ao já adotado no portal do Pulso: verde/âmbar/vermelho aqui
são **semântica de monitoramento**, não selo de oferta. Pintar "tudo certo" de vermelho
seria obedecer a marca e mentir para quem opera. **Não "harmonizar" essas três cores com a
paleta.** O vermelho da marca fica no cabeçalho; o vermelho de alarme é `#C0261F` e serve a
outro propósito.

**Tamanhos (em 1280×800):** PDV 56 px · rótulo de estado 26 px · "PRECISA DE VOCÊ" 34 px ·
cronômetro 88→120 px conforme a gravidade · texto de apoio 18 px. Nada abaixo de 18 px na
tela principal.

## 10. 🔴 Instruções para o Google Stitch — e o que auditar na volta

Gerador de UI **preenche lacuna com número plausível**. Já aconteceu duas vezes nesta casa:
numa landing ele inventou uma audiência 8× maior que a real e ainda escreveu "apurada nos
últimos 90 dias" embaixo; noutro projeto inventou nomes de pessoas e viaturas que não
existem, com o briefing proibindo explicitamente inventar dado. Onde o briefing é explícito
ele obedece; onde é omisso, ele preenche.

Portanto:

- Trate **todo** número que voltar como texto de exemplo — inclusive os que estão neste
  documento. Nenhum vai para produção sem vir do campo real.
- Se aparecer nome de operador, matrícula, produto, valor de compra ou qualquer texto do
  visor: **é violação da regra §3.1**, apaga.
- Se aparecer gráfico, histórico, "média do dia", percentual ou selo de tendência: fora do
  escopo, apaga (§1).
- Se aparecer botão "resolver", "atender", "marcar como visto": apaga (§3.3).
- O código que o Stitch devolve puxa CDN e fonte externa em runtime. **Só o desenho
  interessa** — a implementação segue a convenção da casa (página única, sem build, como o
  portal do Pulso).

### Prompt para colar

> Crie a interface de um painel de monitoramento para tablet 10 polegadas em orientação
> paisagem (1280×800), em português do Brasil, fonte Poppins.
>
> Contexto: uma pessoa que fiscaliza caixas de supermercado carrega este tablet enquanto
> anda pela loja. Ela olha a tela por menos de um segundo por vez, a meio metro de
> distância, sob luz forte. A tela responde a uma única pergunta: "preciso ir até um caixa
> agora?".
>
> Tela principal: cabeçalho vermelho `#CC1F1F` de 56 px com o título "Monitor Fiscal ·
> Castanha OS", relógio, o texto "atualizado há 2 s", um botão de som e uma engrenagem.
> Abaixo, uma grade 2×2 ocupando toda a área restante, com quatro cartões de caixa em
> posições fixas. Cada cartão mostra, centralizado: o número do caixa em 56 px, o estado
> em 26 px maiúsculo, e o tempo naquele estado em 18 px.
>
> Mostre os quatro cartões em estados diferentes na mesma imagem:
> 1. cartão normal — fundo `#FBF8F4`, filete verde `#1F7A4D` de 4 px no topo, número "201",
>    estado "SUBTOTAL", texto "há 12 s";
> 2. cartão normal — número "203", estado "LIVRE", texto "há 1 min";
> 3. **cartão em alarme crítico** — cartão inteiro preenchido de vermelho `#C0261F` com
>    texto branco: número "205" no topo, a frase "PRECISA DE VOCÊ" em 34 px bold, e um
>    cronômetro gigante de 120 px mostrando "1 min 52";
> 4. cartão inativo — cinza `#F2EEE8`, texto `#9A9086`, número "208", rótulo "FECHADO", sem
>    cronômetro.
>
> Rodapé de 48 px, fundo `#FDF3E2`, com o texto "Fora da sua tela: 209 chamando há 34 s".
>
> Regras: sem gráficos, sem histórico, sem percentuais, sem botões de ação nos cartões, sem
> nomes de pessoas, sem valores em dinheiro. Toda cor acompanhada de palavra. Números com
> espaçamento tabular. Estilo limpo, alto contraste, tipografia grande — legível a 1,5
> metros. Não invente dados nem métricas além dos textos citados acima.
>
> Gere também uma segunda tela: lista vertical de treze caixas, cada linha com o número do
> caixa grande, o estado atual em corpo pequeno e uma caixa de seleção grande à direita;
> título "Quais 4 caixas você quer acompanhar?"; botão fixo no rodapé escrito "Usar estes 4".

*(Se o Stitch ignorar instruções em português, traduza as instruções — mas mantenha
intactas todas as strings entre aspas, que são o texto real da interface.)*

## 11. O que este briefing não resolve

- **Como o dado sai do PDV ainda não foi decidido** e é a restrição nº 5 do contrato. A tela
  supõe um back-end que entrega, por caixa, `estado`, `mudou_em` e `visto_em` com latência de
  poucos segundos. **Isso não foi medido.** Enquanto não for, a maquete mostra o formato, não
  prova a promessa.
- **O pareamento do baseline continua aberto:** só 9 a 92 dos 62 a 220 chamados diários
  fecharam par com a autorização. A contagem de chamados é firme; a espera medida é piso, não
  retrato. Sem fechar isso, o "depois" não tem a mesma régua do "antes" e o resultado de
  02/10 não é demonstrável.
- **Nenhum número deste documento é para uso externo.** O contrato proíbe converter para R$:
  não existe valor-hora de cliente em fila aqui, e inventar um queima o informe.
