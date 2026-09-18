# Monitor Fiscal do PDV

Painel de tablet para o **fiscal de loja** — a pessoa que autoriza operações no
caixa, não o documento fiscal. O painel avisa no instante em que um caixa entra
em espera por autorização, para ela chegar antes de o cliente esperar.

Hoje esse chamado é verbal: a operadora levanta a mão, grita ou chama no rádio,
e enquanto isso o cliente fica parado com a compra na esteira.

**Alvo inicial:** self-checkouts **221, 222, 223 e 224** (`192.168.1.121` a `.124`).
**Roda internamente**, em container no servidor. Não vai para a internet.

---

## Estado atual

| | |
|---|---|
| ✅ Painel, com todos os estados | `web/index.html` |
| ✅ Coletor + API | `coletor/monitor.py` |
| ✅ Formato do log confirmado na máquina | `docs/levantamento-self-checkouts.md` |
| ✅ O que pedir ao TI | `docs/pedido-ti.md` |
| ⏳ Acesso `monitorfiscal` nas máquinas | depende do TI |
| ⏳ Barra de volume na tela | back-end pronto, falta a barra |

🔴 **O coletor ainda não rodou com o usuário definitivo.** O levantamento foi
feito por acesso administrativo pontual. Enquanto o TI não configurar o
`monitorfiscal`, o coletor não conecta.

## Rodar

```sh
cp config.example.json config.json      # ajuste as máquinas e a chave
docker compose -f docker/docker-compose.yml up -d --build
# abre em http://<servidor>:8080
```

**Um arquivo, dois modos.** O painel tenta `/api/estado`; se o coletor responder,
roda com dado real. Se não responder, cai numa **banca de prova** com dado
fictício e o selo "PRÉVIA" visível, e continua batendo na porta do servidor a
cada 10 s — quando o coletor sobe, a tela migra sozinha.

Isso é deliberado: duas cópias do mesmo painel divergem em silêncio, e a que
alguém abre no tablet nunca é a que foi corrigida.

Na banca de prova, o canto inferior direito dispara cada cenário: chamado novo,
estouro dos 60 s, coletor morto, caixa fechado, chamado fora da tela e a variante
em tela cheia.

## API

| | |
|---|---|
| `GET /api/estado` | estado de todas as máquinas |
| `GET /api/volume?pdv=221` | lê o volume |
| `POST /api/volume` `{"pdv":221,"volume":70}` | grava e **devolve o volume lido de volta** |

`/api/estado` **nunca devolve texto de visor**. O coletor reduz o conteúdo do
bloco a um hash só para detectar mudança e descarta o texto — não existe caminho
de código que exponha nome de operador nem valor de compra.

**A cesta da sessão em andamento, essa sim, é servida** (`itens`), do item mais
recente para o mais antigo, com quantidade.

> A API manda do **mais recente para o mais antigo**; o painel exibe **na ordem
> em que o cliente passou** (primeiro em cima, último embaixo). A inversão é de
> apresentação e mora no `listaItens()` do front-end — a ponta "mais recente
> primeiro" é de onde saem `item` e o corte em `max_itens`, e por isso fica.
> Como o item novo nasce embaixo, a lista **gruda no fim** e desce sozinha; se o
> fiscal subir para ler o começo da compra, a posição dele é respeitada. Ela existe só em memória, no máximo
`max_itens` linhas por caixa (30), e é apagada inteira quando a máquina entra em
`SCREENSV/IDLE/CLOSED/Z/HELLO/THANKYOU` — ou seja, morre junto com o cliente que
a gerou. Nada disso vai para disco, log ou fora da rede.

```json
"itens": [{"d": "REFRIG.COCA COLA 2LT", "q": 2, "ha": 4.1}, ...],
"itens_lidos": 7,
"item": "REFRIG.COCA COLA 2LT"
```

`item` é o mais recente e continua existindo só para o tablet que ficou com a
página antiga em cache. `itens_lidos` conta as leituras da sessão que o catálogo
resolveu — é com ele que a tela sabe dizer "+N itens antes, fora da memória"
quando a compra passa de `max_itens`.

### Ações na máquina (⚙ no cabeçalho)

A tela de "quais 4 caixas acompanhar" virou tela de **ações**: um botão por caixa
e, dentro, duas ações. A antiga era um no-op — a loja tem 4 self-checkouts e o
painel mostra 4, então a escolha era sempre a mesma.

| Ação | O que roda no PDV |
|---|---|
| Barra de volume | `amixer sset Master N%` + `alsactl store` |
| Destrava Self | `pkill vend` (o `!pk`) |
| Reinicia Self | `reboot` |

**A barra de volume** lê o valor ao abrir o caixa e só então se habilita —
enquanto não leu, mostra "…". Aplica no `change` (soltar), não no `input`, senão
um arrasto viraria dezenas de conexões SSH. O número que aparece é o que a
**máquina respondeu**, não o que a barra pediu: comando aceito não é comando
aplicado.

🔴 **Piso de 30%, nas duas pontas** (servidor e roteiro). Sem ele alguém arrasta
até zero, o self-checkout fica mudo, e ninguém liga o fato ao painel.

🔴 **Nunca escrever antes de ter lido.** Sem essa guarda, um `change` que o
próprio redesenho dispara aplica na máquina o valor *default* da barra. Aconteceu
em teste em 10/09: os PDVs 221, 222 e 223 foram de 82% para 70% sem ninguém
encostar na barra. Numa tela pendurada na loja isso é pior do que parece —
o volume cai sozinho e ninguém associa ao painel. Hoje o `change` é ignorado
enquanto `volAtual` for nulo, e também quando o valor não mudou.

**`alsamixer` não serve** — é tela interativa e não aceita parâmetro. Quem serve
é o `amixer`, como o `docs/pedido-ti.md` já registrava.

**O `mf-agente` continua só leitura.** Chegou a ser considerado liberar
`volume-definir` nele (o próprio script diz que ficou de fora "até a barra de
volume existir de verdade"), e foi descartado: como o canal de root já está em
uso para destravar e reiniciar, mexer no script de segurança de quatro máquinas
de produção não compraria segurança nenhuma.

**Como chega lá.** A chave `monitorfiscal` está presa a `command=` e só aceita a
lista do `mf-agente` — comando arbitrário por ela responde "comando nao
permitido". Como o PDV aceita root por senha, o caminho é o `acao-pdv.exp`
(expect), e **nada precisou mudar nas máquinas**.

🔴 **O comando não vem da rede.** O servidor passa o NOME da ação; é dentro do
`acao-pdv.exp` que "destrava" vira `pkill vend`. Nome fora da lista é recusado —
testado com `reboot; rm -rf /` como parâmetro, nos dois níveis (API e script). A
senha fica em `.senha-pdv` com permissão 600 e é lida do arquivo, nunca passada
por argumento, que apareceria na lista de processos.

**Três travas no destrutivo**, e nenhuma é decoração:
1. confirmação na tela, com o número do caixa e aviso quando há venda aberta;
2. `intervalo_acao` (30 s) recusa repetir a mesma ação no mesmo caixa — toque
   duplo em tablet é regra, não exceção;
3. toda ação vai para o log do coletor, senão ninguém responde depois "quem
   reiniciou o 224 às 11h".

Há uma ação `teste` na API que não aparece na tela: roda um `echo` do outro lado
e serve para conferir que o canal está vivo sem tocar no venditor.

```sh
curl -s -X POST -H 'Content-Type: application/json'   -d '{"pdv":224,"acao":"teste"}' http://127.0.0.1:8080/api/comando
```

### PIN na entrada do painel

`pin_acoes` no `config.json`. Vazio ou ausente deixa o painel aberto.

O painel **nasce trancado**. Digita o PIN, o servidor devolve um token de sessão,
e a partir daí toda chamada leva esse token no cabeçalho `X-MF-Token`.

🔴 **A tranca é no SERVIDOR, não na tela.** Overlay de PIN no navegador seria só
uma cortina: bastaria pedir `/api/estado` direto para ver o estado dos caixas
**e a cesta de quem está comprando naquele momento**. O que o servidor barra é o
dado, não a tela.

| | |
|---|---|
| `/api/entrar` | único caminho aberto — é por ele que se obtém a sessão |
| `/api/estado`, `/api/volume`, `/api/comando` | 401 sem token válido |
| a página em si | servida normalmente; sem token ela não mostra nada |

- **Recarregar pede o PIN de novo.** O token vive só em memória — nada de
  `localStorage` nem cookie. Guardar em disco faria o oposto do pedido: abriria
  sozinho para sempre depois da primeira vez.
- `hmac.compare_digest` e não `==`: comparação normal para no primeiro caractere
  diferente, e isso vaza o PIN pelo tempo de resposta.
- **Cinco erros seguidos do mesmo IP travam por 60 s.** Quatro dígitos são 10 mil
  tentativas, e uma rede de loja é rápida.
- Sessão ociosa morre em `sessao_validade` (12 h). Uma aba aberta se renova
  sozinha, porque o painel pergunta a cada 500 ms; o prazo só limpa o que ficou
  para trás.
- Trancado, o painel **não pergunta nada** — sem token a API recusa, e insistir
  só encheria o log de 401.

Trocar o PIN: editar `pin_acoes` e reiniciar o coletor.

### Publicar: sempre atômico

🔴 **Nunca copie por cima do arquivo em uso.** O `pscp`/`scp` escreve no lugar, e
uma página carregada durante o upload pega o arquivo pela metade: o JavaScript
vem truncado, o script morre com erro de sintaxe e o painel **congela no último
desenho** — com a animação do CSS continuando, então a célula fica piscando um
alerta já resolvido, para sempre. Nenhum código em página se recupera disso,
porque o JS já morreu.

Aconteceu em 09/09 no tablet da loja, depois de o `index.html` ser publicado
umas dez vezes numa tarde.

```sh
pscp arquivo root@192.168.1.108:/root/monitor-fiscal/web/index.html.novo
ssh root@192.168.1.108 'cd /root/monitor-fiscal && sh publicar.sh web/index.html'
```

`publicar.sh` valida antes de trocar (HTML tem de fechar `</html>` e ter as tags
de script balanceadas; `.py` tem de compilar) e usa `mv`, que no mesmo sistema de
arquivos é atômico: quem está lendo pega o arquivo velho inteiro ou o novo
inteiro, nunca um pedaço dos dois.

**Como reconhecer um painel congelado:** o "atualizado há X" no cabeçalho para de
dizer "agora", cresce e fica vermelho. A tela continua bonita e mentindo. A cura
é recarregar a página no tablet.

### Impressora: as duas falhas são sinais DIFERENTES

O painel não avisava quando a impressora caía. A causa, medida em 09/09 com o
Valmir mexendo no 224: **o estado da máquina não muda**. Continua `HELLO(19)`,
igual ao "Passe o item no leitor" do segundo anterior.

E os dois defeitos não se parecem em nada:

| Defeito | O que a máquina faz | De onde vem o sinal |
|---|---|---|
| Impressora **desligada / cabo solto** | não responde → escreve no visor "Impressora nao responde, verificar cabos" | `display.log`, por texto |
| Impressora **sem papel** | responde normal e **deixa vender calada** | `venditor.log`, status estruturado |

🔴 **Papel acabado não produz mensagem nenhuma no visor.** Foi medido: com a
bobina fora do 224, a captura do `display.log` saiu vazia de qualquer menção a
papel ou impressora, e o PDV seguiu registrando itens. Chegou a haver padrões de
texto do tipo `"sem papel"` no código — eram palpite e foram **removidos**.

O sinal certo é o `gstTicketStatus`, que o venditor grava ao consultar a
impressora:

```
iSERIAL_Status PAPER RslByte[r] 0x72 114
iSERIAL_Status - gstTicketStatus ===================================
       bLowPaper[0]      bNoPaper[1] Date[09-09-2026] Time[12:07:28]
```

Conferido nos dois estados no mesmo instante: PDV 121 com papel dava
`bLowPaper[0] bNoPaper[0]` (byte `0x12`), PDV 224 sem papel dava
`bNoPaper[1]` (byte `0x72`).

**`bLowPaper` é lucro:** avisa que a bobina está acabando *antes* de o caixa
parar. Não pinta a célula de vermelho — a máquina ainda vende, e vermelho para
algo que não trava seria o começo do "vermelho de papel de parede" que este
painel evita desde o início. Aparece como aviso no rodapé da célula.

**`limiar_papel` = 90 s** (no `config.json`). É por quanto tempo a última
leitura continua valendo como *afirmação*. Passado isso, "sem papel" deixa de ser
vermelho e vira aviso de leitura velha, com a idade na tela.

A escolha é do Valmir, em 10/09, depois de trocar a bobina e o painel seguir
vermelho por 5 minutos: **alerta que apaga sozinho com o papel ainda fora se
corrige na próxima venda, mas vermelho falso corrói a confiança no vermelho** — e
aí o alarme que importa morre junto. Em troca, pode piscar durante venda
movimentada: o maior intervalo medido entre consultas do venditor à impressora
foi ~2,7 min, acima do limiar.

**Para apagar na hora, inicie uma venda no caixa.** Passar um item força a
consulta e o painel corrige em segundos, nos dois sentidos.

Foi considerado e **descartado** fazer o painel perguntar direto à impressora: a
porta serial é do venditor, e um segundo processo falando nela pode atrapalhar a
comunicação dele. Trocar alerta atrasado por cupom corrompido seria mau negócio.

⚠️ **Limite honesto:** o status só é gravado quando o venditor **consulta** a
impressora, o que acontece durante as vendas (medido: várias vezes por venda,
com intervalos de até ~3 min entre uma venda e outra). Máquina parada não
consulta. Então, depois de um restart do coletor, o papel de um caixa ocioso
fica **desconhecido** até a primeira venda — e `papel` nulo não inventa alarme
nenhum, que é o comportamento correto.

O teste está em `teste-falha.py`, com as linhas reais das duas capturas, e
inclui uma varredura que falha se qualquer pedaço do texto do visor — ou a
matrícula da fiscal — aparecer na resposta da API.

### Alerta sonoro

**Dois tons alternados**, tipo interfone — escolhido pelo Valmir em 08/09
ouvindo as opções no próprio tablet da loja. A banca de prova ficou em
`/sons.html` (não faz parte do painel; serve para escolher ou re-escolher o som).

O alerta antigo saía baixo demais mesmo com o tablet no máximo, por dois motivos
somados — e o segundo pesava mais:

1. o ganho de pico era `0.18`, 18% da escala;
2. as notas ficavam entre 880 e 660 Hz, **abaixo da faixa que um alto-falante de
   tablet reproduz**. São transdutores pequenos e sem caixa acústica: rendem bem
   de ~1,5 kHz para cima e despencam abaixo disso. Por isso subir o volume do
   sistema não resolvia — faltava eficiência do alto-falante naquela frequência,
   e isso volume não compra.

Hoje o par mais grave ainda fica em 1,5 kHz, dentro da faixa útil.

🔴 **O saturador não é enfeite.** Pedir "volume 2" na banca fazia o som *cortar*:
pico 1,19 com 7.397 amostras no teto. Baixar o ganho interno quase não ajudava,
porque o compressor já normaliza e multiplicar a saída por 2 estoura de qualquer
jeito. A saída foi um saturador `tanh` (WaveShaper), limitado a ±1 por
construção — e os harmônicos que ele cria caem justamente na faixa que o
transdutor reproduz bem, então ajudam em vez de atrapalhar.

Medido na função real do painel, em `OfflineAudioContext`, a 44,1 e 48 kHz:

| degrau | pico | amostras no teto |
|---|---|---|
| 0 | 0,931 | 0 |
| 1 | 0,930 | 0 |
| 2 | 0,930 | 0 |
| 3 | 0,930 | 0 |

`VOLUME_ALERTA` é o ajuste de campo. Parou em `1.3` porque o saturador dá
retorno decrescente: de 1.3 para 1.9 ganha **0,5 dB**, que ninguém distingue, e
o pico sobe para 0,973 — perto demais do teto para um aparelho que pode se
comportar diferente do teste. Até 1.6 foi medido limpo. Acima disso, o caminho é
uma caixinha USB ou Bluetooth: há um limite físico no alto-falante que software
não vence.

A escada de urgência continua: os degraus 2 e 3 tocam três pares em vez de dois
e ficam 2 dB acima do degrau 0.

### Sacolinha

A sacola **não é bipada** — e é por isso que ela nunca aparecia. Gravei 13.662
linhas do 221 em 08/09 durante uma compra com sacola: o EAN do produto
(`7908531400807 SACOLINHA BIOP.48X55`, que sai no dump da NFC-e no fim da venda)
**não aparece uma única vez** no log. Ela entra por um controlador externo:

```
./ftself --command=qty-bag --list-items=7899498703011,7898257751348 ...
  BAG_QTY1=[0]     <- a máquina oferecendo
DISPLAY Deseja sacola
  BAG_QTY1=[1]     <- o cliente aceitou
```

`--list-items` traz um código por tipo de sacola, na ordem dos `BAG_QTY`.

🔴 **A quantidade aqui é ABSOLUTA**, não um evento de leitura: a máquina
reimprime o valor corrente a cada aperto de +/−. Por isso a sacola usa
`define_item` (fixa a quantidade) e não `registra_item` (soma um) — somando,
uma sacola viraria 3. Como efeito, ver o mesmo valor de novo não muda nada, e a
repetição no log é inofensiva. `BAG_QTY` igual a zero remove: é assim que a
máquina diz que o cliente desistiu.

Os códigos do `--list-items` **não estão no PLU exportado**, então o catálogo
não resolve o nome. Quem sabe qual é qual é o `nomes_sacola` do `config.json`:

```json
"nomes_sacola": {
  "7899498703011": "SACOLA VERDE 48X55",
  "7898257751348": "SACOLA CINZA 48X55"
}
```

Sem essa chave o painel mostra `SACOLA` e `SACOLA TIPO 2`, que já é a informação
que o fiscal precisa (levou sacola, e quantas).

Isso **não afrouxa o filtro do catálogo**: o caminho da sacola não traduz número
nenhum lido do scanner, então não há por onde uma matrícula entrar — o gatilho é
o nome do comando (`qty-bag`) e o dado é um inteiro pequeno.

O teste está em `teste-sacola.py` e reproduz a sequência gravada linha por linha.

### Item de balança

O que o scanner lê num item pesado não é um SKU: é um EAN-13 com o **preço
embutido**, então o número inteiro nunca está no PLU. Medido ao vivo em 07/09
nos quatro caixas: **4 de 7 leituras (57%) caíam fora** — hortifrúti, padaria,
açougue e frios, uma fatia enorme da cesta, invisível no painel.

```
2  7340  00  03024  5
|  |     |   |      +-- dígito verificador
|  |     |   +--------- valor em centavos (R$ 30,24)
|  |     +------------- resto do campo de código, de 6 dígitos, zerado
|  +------------------- PLU (4 dígitos — é o cadastro de balança da loja)
+---------------------- prefixo 2 = item pesado
```

A leitura é **fixa** nas posições 2 a 5, e o `00` no meio é obrigatório.

🔴 **Não trocar por "o prefixo mais longo que existir no PLU".** Foi testado e
produz nome errado: `2118600002541` casa com o PLU `11860` = "ESPONJA BANHO
BUZATO" quando o item é o PLU `1186` = "CEBOLA COMUM KG". Num painel fiscal,
nome errado é pior que nome nenhum.

Isso não abre porta para a matrícula da fiscal aparecer: ela tem 8 dígitos e não
casa com um padrão de 13. O catálogo continua sendo a única porta de entrada.

O teste está em `teste-balanca.py` e roda contra o PLU real, cobrindo os cinco
códigos medidos, o caminho do EAN comum e os quatro casos que **precisam** ser
descartados.

## Primeiro deploy: o que esperar

Vale subir **antes** de o TI configurar as máquinas — assim se valida tudo que
não depende dos PDVs: a imagem constrói, a porta responde, o tablet abre a página
e o servidor alcança os self-checkouts.

```sh
git clone git@github.com:Castanha-ti/monitor-fiscal.git
cd monitor-fiscal
cp config.example.json config.json
docker compose -f docker/docker-compose.yml up -d --build
```

Abra `http://<ip-do-servidor>:8080` no tablet.

🟡 **As quatro células vão aparecer como "sem sinal", e isso está certo.**
Enquanto o usuário `monitorfiscal` não existir nas máquinas, o coletor não
conecta — e a célula mostra o motivo da falha em vez de um cinza mudo. O painel
não vai fingir que está tudo bem: é a regra nº 2 funcionando.

Para trocar a porta, ajuste `porta` no `config.json` **e** o mapeamento em
`docker/docker-compose.yml` — os dois precisam bater.

### Conferir sem abrir o navegador

```sh
curl -s http://127.0.0.1:8080/api/estado | head -40
docker logs -f monitor-fiscal
```

O log do container mostra, por máquina, a razão de cada falha de conexão.

## As regras que o código precisa honrar

Não são preferência de design. Quebrar qualquer uma invalida o painel.

**1. Só o campo de ESTADO vai para a tela.** O log de origem traz nome completo
do operador, matrícula, nome de produto e valor da compra do cliente. Nada disso
pode ser renderizado, nem em tooltip, nem em "detalhe". É base legal.

**2. Ausência de dado tem cor própria.** Um painel cego que aparenta calma é pior
que painel nenhum. Quando o coletor para de falar, a célula vira "sem sinal", com
aparência distinta tanto de "tudo certo" quanto de alarme — e o rótulo de estado
passa a dizer *"último: …"*, porque virou lembrança, não leitura.

**3. Dois relógios distintos, nunca um.**

| campo | o que é | para que serve |
|---|---|---|
| `mudou_em` | última mudança de visor | o "há 12 s" da célula calma |
| `visto_em` | último batimento do coletor: *"li o arquivo, e nada mudou"* | **o único** que dispara "sem sinal" |

O arquivo de log **só cresce quando o visor muda**: caixa ocioso não escreve
nada. Confundir os dois transforma caixa vazio às 9h da manhã em alarme, e o
painel é desligado na primeira semana.

**4. Não existe botão "resolvido".** O episódio fecha sozinho quando a
autorização acontece no caixa. Passo manual em processo de rotina não acontece.

**5. Escrita no caixa passa por via estreita.** O ajuste de volume é a única
escrita prevista, e entra por chave SSH restrita a um script com três comandos
(`docs/pedido-ti.md`). O painel mostra o volume que a máquina **respondeu**, não
o que o controle deslizante mandou.

## A escada de alerta

O chamado nasce vermelho e escurece com o tempo, piscando cada vez mais rápido.
Os três primeiros tons são os vermelhos oficiais da marca.

| espera | cor | pisca |
|---|---|---|
| 0 s | `#E8443A` Vermelho Vivo | 2,2 s |
| 15 s | `#CC1F1F` Vermelho Castanha | 1,4 s |
| 40 s | `#991515` Vermelho Fundo | 0,9 s |
| **60 s** | `#6B0E0E` | 0,6 s + vibração |

Os 60 s são a meta escrita no contrato: **nenhum episódio acima de 60 s**. Hoje o
pior caso medido passa de 5 minutos.

## O que falta decidir antes de construir o back-end

1. **Medir o baseline nos self-checkouts.** Os 62 a 220 chamados/dia do contrato
   foram medidos num caixa **tradicional**. Self-checkout chama fiscal por
   verificação de idade, divergência de peso e item não lido — outra ordem de
   grandeza. Sem baseline novo, o "antes" não é régua do "depois".
2. **Confirmar o formato do log** do self-checkout.
3. **Confirmar o nome do controle de mixer** (`amixer scontrols`) — pode não ser
   `Master`.

---

Desenvolvido por Rodolfo Almeida · Castanha OS
