#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Monitor Fiscal — coletor e API.

Mantem um `tail -F` por self-checkout, via SSH, e serve o estado de todos
em JSON para o tablet.

REGRAS QUE ESTE ARQUIVO PRECISA HONRAR (nao sao estilo):

1. O texto do visor NUNCA e guardado nem servido. O log traz
   "Fiscal <matricula> (NOME COMPLETO)", nome de produto e valor de compra.
   Aqui o texto e reduzido a um HASH so para detectar mudanca, e descartado.
   Nao existe caminho de codigo que exponha o texto -- isso e estrutural,
   nao uma regra de disciplina.

2. Maquina que para de falar vira "sem sinal", nunca some e nunca fica verde.
   No self-checkout o log grava um bloco POR SEGUNDO mesmo parado, entao
   silencio AQUI e falha -- ao contrario do PDV tradicional, onde silencio e
   so operador ocioso.

3. Dois relogios distintos: `mudou_em` (o bloco mudou de conteudo) e
   `visto_em` (chegou alguma linha). So `visto_em` decide "sem sinal".

Medido em 02/09/2026 nas quatro maquinas, 25/08 a 02/09:
756 episodios de AUTH, media 2,7 s, pior caso 13 s, nenhum acima de 30 s.
E por isso que existe LIMIAR_ALERTA: avisar em todo AUTH seria avisar ~37
vezes por dia por maquina, quase sempre por 3 segundos. O painel so acende
quando passa do que o fiscal ja resolve sozinho.
"""

import json
import hashlib
import hmac
import secrets
import os
import re
import shlex
import subprocess
import sys
import threading
import time
import unicodedata
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

AQUI = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.environ.get("MF_CONFIG", os.path.join(AQUI, "..", "config.json"))

# Cabecalho de bloco:
# ------------------ AUTH(68) 5/0 1 02/09/26 08:01:16 180
CABECALHO = re.compile(
    r"^-{20,}\s+(?P<estado>\S+?)\s+(?P<cod>\d+/\d+)\s+\S+\s+"
    r"(?P<data>\d\d/\d\d/\d\d)\s+(?P<hora>\d\d:\d\d:\d\d)\s+(?P<seq>\d+)\s*$"
)
NOME_ESTADO = re.compile(r"^([A-Za-z_]+)(?:\((\d+)\))?$")

# No venditor.log, tudo que o terminal le entra assim:
#     iINQ_Ins_Tail from=0x0010 cmd=3 cmd-data=[<null>] data=[7896003737417]
#
# 🔴 A MATRICULA DA FISCAL ENTRA PELO MESMO CANAL, com o formato identico
# (`from=0x0010 cmd=3`): `data=[30017412]`. Nao existe campo que separe os dois.
# Quem separa e o CATALOGO: so vira item na tela o numero que existe como SKU no
# PLU da maquina. Uma matricula nao esta no PLU e e descartada em silencio.
#
# Isso e estrutural, nao uma checagem que da para esquecer: sem o catalogo, nada
# aparece. O residuo conhecido e uma matricula que por coincidencia seja igual a
# um EAN-8 -- apareceria um nome de produto errado, nunca a identidade da pessoa.
#
# 🔴 CADA LEITURA APARECE DUAS VEZES no venditor.log, com o MESMO `data=[]`:
#     iINQ_Ins_Tail    from=0x0001 cmd=3 cmd-data=[<null>] data=[2734000030245] trn=0
#     pstINQ_Read_Head from=0x0001 cmd=3 cmd-data=[<null>] data=[2734000030245] ... remove=1
# Enquanto o painel guardava SO o ultimo item isso era inofensivo: a segunda
# linha sobrescrevia a primeira com o mesmo valor. Numa LISTA duplicaria todos.
# So a linha de INSERCAO conta -- a outra e a leitura da fila, nao um item novo.
DADO_LIDO = re.compile(r"iINQ_Ins_Tail\b.*?data=\[(\d{6,14})\]")

# Etiqueta de BALANCA, EAN-13 com o preco embutido:
#
#     2  7340  00  03024  5
#     |  |     |   |      +-- digito verificador
#     |  |     |   +--------- valor em centavos (R$ 30,24)
#     |  |     +------------- resto do campo de codigo, que tem 6 digitos e
#     |  |                    sobra zerado porque o PLU da loja tem 4
#     |  +------------------- PLU (4 digitos, confirmado pelo Valmir em 07/09)
#     +---------------------- prefixo 2 = item pesado
#
# Conferido em cinco leituras reais, e a primeira delas de forma INDEPENDENTE:
# o dump da NFC-e no proprio venditor.log lista "Q PARMESAO CUNHA KG" na mesma
# compra em que 2734000030245 foi lido.
#     2734000030245 -> 7340 Q.PARMESAO CUNHA KG
#     2118600002541 -> 1186 CEBOLA COMUM KG
#     2113600005127 -> 1136 MARACUJA AZEDO KG
#     2529100015526 -> 5291 CAKE CHOCOLATE KG
#     2108400007679 -> 1084 BRIGADEIRO KG
#
# Isto NAO abre porta para a matricula da fiscal aparecer: ela tem 8 digitos
# (`data=[30017412]`) e nao passa por um casamento de 13. O filtro do catalogo
# continua sendo a unica porta de entrada.
BALANCA = re.compile(r"^2(\d{4})00\d{6}$")

# A SACOLINHA NAO E BIPADA -- e o motivo de ela nunca ter aparecido no painel.
# Gravei 13.662 linhas do 221 em 08/09 durante uma compra com sacola: o EAN do
# produto (7908531400807 SACOLINHA BIOP.48X55, que sai no dump da NFC-e no fim
# da venda) NAO aparece uma unica vez no log. Ela entra por um controlador
# externo, num canal proprio:
#
#   iOS_ExternalController try [./ftself --command=qty-bag
#       --list-items=7899498703011,7898257751348 --layout-bag=96 ...]
#     BAG_QTY1=[0]        <- a maquina oferecendo
#   DISPLAY Deseja sacola
#     BAG_QTY1=[1]        <- o cliente aceitou
#
# `--list-items` traz um codigo por tipo de sacola, na ordem dos BAG_QTY. Os
# dois codigos desta loja NAO estao no PLU exportado, entao o nome vem de
# `nomes_sacola` na config; sem isso, o rotulo generico.
#
# A quantidade aqui e ABSOLUTA, nao um evento de leitura: a maquina reimprime o
# valor corrente a cada aperto de +/-. Por isso a sacola usa `define_item`
# (fixa a quantidade) e nao `registra_item` (soma um).
#
# Isto NAO afrouxa o filtro do catalogo. O caminho da sacola nao traduz numero
# nenhum lido do scanner -- nao ha por onde uma matricula entrar: o gatilho e o
# nome do comando (`qty-bag`), e a quantidade e um inteiro pequeno.
SACOLA_LISTA = re.compile(r"--list-items=([\d,]+)")
SACOLA_QTD = re.compile(r"\bBAG_QTY(\d+)=\[(\d+)\]")

# Estados que significam "esperando alguem com credencial".
#
# Casado por NOME + CODIGO, nao so pelo nome: `extra` sozinho serviria para tres
# coisas diferentes e acenderia o painel a toa.
#   AUTH(68)   autorizacao geral -- "Menu de Funcoes / Fiscal?"
#   extra(33)  BEBIDA ALCOOLICA -- descoberto em 03/09 lendo o que o estado
#              `extra` significava. O ciclo vai de "Bebidas Alcolicas" ate
#              "Fiscal <matricula>", e o painel nao enxergava NADA disso: era
#              uma classe inteira de chamado invisivel. Hoje sao ~94 blocos por
#              dia nas quatro maquinas contra ~896 do AUTH.
# Os outros dois `extra` NAO sao chamado:
#   extra(74)  a maquina perguntando ao cliente (sacola, NF Paulista)
#   extra(31)  "Passe o proximo item", com o contador
CHAMADO = {("AUTH", 68), ("extra", 33)}

# Chamados de ROTINA: previsiveis, a fiscal sabe de cor o que fazer. Nascem
# ambar com contador em vez de vermelho, e SOBEM para vermelho se ninguem
# atender (`limiar_rotina`).
#
# Decisao do Rodolfo em 03/09, e a razao e boa: sao ~38 autorizacoes de bebida
# por dia. Se cada uma pintar a tela de vermelho por tres segundos, o vermelho
# vira papel de parede e o alarme que importa -- divergencia de peso, que e
# imprevisivel -- se perde no meio.
#
# A escalada existe porque ambar puro seria a cor de "venda normal": sem ela,
# uma bebida esquecida ficaria invisivel, que e exatamente o buraco que o
# extra(33) tinha antes de ser descoberto.
CHAMADO_ROTINA = {("extra", 33)}

# ---------------------------------------------------------------------------
# FALHA DE EQUIPAMENTO NO VISOR
#
# Gravado no 224 em 09/09 as 11:22, com o Valmir desligando a impressora:
#     ---------------------------------------- HELLO(19)
#      0/0 1 09/09/26 11:22:47 530
#     Impressora nao responde, verificar cabos
#     TECLE ENTRA
#
# 🔴 O ESTADO NAO MUDA. Continua `HELLO(19)`, igual ao "Passe o item no leitor"
# do segundo anterior. Quem muda e o TEXTO -- e o texto era exatamente a unica
# coisa que este arquivo se recusava a olhar. Resultado: o caixa ficava ambar
# "iniciando", com a impressora morta, e o painel nao dizia nada. So depois de
# 120 s de visor parado ele viraria "tela parada", que e tarde e nao explica.
#
# A REGRA DO TEXTO CONTINUA VALENDO. O corpo do bloco e CLASSIFICADO aqui e
# descartado no mesmo metodo, como sempre foi: o que sobrevive e uma etiqueta
# de categoria ("impressora"), nao o texto. Nao existe caminho que leve o
# conteudo do visor para a memoria, para a API ou para a tela -- e isso e
# estrutural, do mesmo jeito que o hash e.
#
# Os padroes sao configuraveis (`padroes_falha` no config.json) porque so um
# deles foi CONFIRMADO em campo: o da impressora desligada. Os de papel sao
# palpite informado e precisam ser conferidos com o texto real da maquina --
# ate la, papel acabado pode nao acender.
# 🔴 SO ENTRA AQUI O QUE FOI CONFIRMADO EM CAMPO. Cheguei a por palpites de
# "sem papel"/"falta papel" e tirei: papel acabado NAO produz mensagem nenhuma
# no visor -- medido em 09/09, com o Valmir tirando a bobina do 224 e a captura
# do display.log saindo VAZIA de qualquer mencao a papel ou impressora. A
# maquina deixa vender normalmente. Papel agora vem do STATUS_PAPEL, abaixo,
# que e sinal estruturado e nao adivinhacao.
FALHAS_PADRAO = {
    "impressora": [
        "impressora nao responde",   # confirmado no 224, 09/09 11:22
        "verificar cabos",           # confirmado no 224, 09/09 11:22
    ],
}

# ---------------------------------------------------------------------------
# PAPEL DA IMPRESSORA — sinal estruturado, nao texto de visor.
#
# O venditor consulta a impressora e imprime o resultado no venditor.log:
#
#   iSERIAL_Status PAPER RslByte[r] 0x72 114
#   iSERIAL_Status - gstTicketStatus ==========================================
#          bLowPaper[0]      bNoPaper[1] Date[09-09-2026] Time[12:07:28]
#
# Medido em 09/09 com a bobina fora do 224 e as outras maquinas normais:
#   PDV 121 (com papel)  bLowPaper[0] bNoPaper[0]   byte 0x12
#   PDV 224 (sem papel)  bLowPaper[0] bNoPaper[1]   byte 0x72
# O campo alterna, entao da para confiar nele.
#
# `bLowPaper` e o presente de graca: avisa que a bobina esta acabando ANTES de
# o caixa parar. Nao pinta a celula de vermelho -- a maquina ainda vende, e
# vermelho para algo que nao trava seria o comeco do "vermelho de papel de
# parede" que este painel evita desde o inicio.
#
# A leitura so acontece quando o venditor consulta (inicio de venda e durante
# ela). Entre consultas vale a ULTIMA lida, o que e o comportamento correto:
# papel fora continua fora ate alguem trocar.
STATUS_PAPEL = re.compile(r"bLowPaper\[(\d)\]\s+bNoPaper\[(\d)\]")

# ---------------------------------------------------------------------------
# BEBIDA ALCOOLICA PAGA COM VALE (pedido do Valmir, 14/09)
#
# Vale refeicao/alimentacao nao pode pagar bebida alcoolica, e o self-checkout
# NAO bloqueia: gravado no 224 em 14/09, com uma CERV.SKOL LT.350ML na cesta,
# a maquina aceitou as duas finalizadoras e foi direto pedir o cartao:
#   14:51:57 iINQ_Ins_Tail from=0x0001 cmd=5 cmd-data=[17] data=[]
#   14:51:57 iCMD_Media check value [Vale Refeicao]
#   14:51:57 ---- lCallLibSitef begin iMode=0 iMediaCode=17 dAmount=3.9900
#   14:52:41 iCMD_Media check value [Vale Alimentacao]      (codigo 6)
#
# A linha `check value` sai no TOQUE na finalizadora, antes do cartao -- e o
# momento em que a fiscal ainda consegue chegar. O nome e o que vale, e nao o
# codigo: e o que a loja reconhece e o que da para por na config.
MIDIA = re.compile(r"iCMD_Media check value \[([^\]]*)\]")

# Congelar Self: o `acao-pdv.exp` agenda a soltura automatica neste prazo. Os
# dois lados precisam do MESMO numero -- se o painel achar que ainda esta
# congelado depois que a maquina soltou, a fiscal nao vai la.
CONGELA_MAX = 600
# O roteiro responde o estado REAL do processo (`ps`): T = parado.
CONGELA_ESTADO = re.compile(r"^MF-ESTADO-([A-Z])\s*$", re.M)
CONGELA_SEM = re.compile(r"^MF-SEM-VENDITOR\s*$", re.M)
VALES_PADRAO = ("Vale Refeicao", "Vale Alimentacao")

# O que e bebida alcoolica sai do NCM do proprio PLU (terceira coluna do
# `plu-mapa-ncm`). Medido no PLU de 14/09: 3.135 itens.
#   2203 cerveja  2204 vinho  2205 vermute  2206 fermentadas (sidra, ice)
#   2208 destilados
# FORA, de proposito:
#   2207 alcool etilico -- no cadastro e ALCOOL GEL, alcool de limpeza e gel
#        acendedor, nao bebida;
#   2202 bebida nao alcoolica -- inclui CERVEJA LIBER e ITAIPAVA ZERO.
# Nao usar o DEPT_ID: o departamento das bebidas tambem tem etiqueta, papel e
# carregador. Erro de cadastro (MIKES HARD LEM.300ML sem NCM, MARTINI BIANCO com
# NCM de copo) corrige-se no ERP -- ou, ate la, em `alcool_incluir`.
NCM_ALCOOL_PADRAO = ("2203", "2204", "2205", "2206", "2208")


def normaliza_midia(nome):
    """'Vale Refeição' e 'VALE  REFEICAO' sao a mesma finalizadora."""
    s = unicodedata.normalize("NFKD", str(nome or ""))
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return " ".join(s.upper().split())


def _achatado(texto):
    """minusculas, sem acento e com espaco normalizado.

    O log nao e UTF-8 e escreve "nao" sem til, mas nada garante que toda
    mensagem seja assim -- comparar achatado evita depender disso.
    """
    t = unicodedata.normalize("NFKD", texto)
    t = "".join(c for c in t if not unicodedata.combining(c))
    return " ".join(t.lower().split())


def classifica_falha(corpo, padroes):
    """Devolve a CATEGORIA da falha vista no visor, ou None.

    Recebe o texto e devolve uma etiqueta. O texto morre aqui.
    """
    achatado = _achatado(corpo)
    for categoria, marcas in padroes.items():
        for m in marcas:
            if m in achatado:
                return categoria
    return None


def e_chamado(estado, codigo):
    if (estado, codigo) in CHAMADO:
        return True
    # AUTH sem codigo continua valendo: e o mesmo estado, so sem o parenteses.
    return estado == "AUTH"

# Estados que significam "nao ha cliente transacionando agora". Ao entrar em
# qualquer um deles o ultimo item e APAGADO.
#
# Sem isso o item vaza de um cliente para o outro: o primeiro passa um
# refrigerante, vai embora, e o proximo pede autorizacao antes de passar
# qualquer coisa -- o painel mostraria a compra de quem ja saiu, durante o
# atendimento de outra pessoa. Errado como informacao e indefensavel como
# tratamento de dado.
ESTADOS_FIM_DE_SESSAO = {"SCREENSV", "IDLE", "CLOSED", "Z", "HELLO", "THANKYOU"}
# Estados de maquina fora de operacao — nao sao problema e nao podem parecer.
ESTADOS_INATIVOS = {"CLOSED", "Z"}


def agora():
    return time.time()


def _hora_txt(t):
    return time.strftime("%d/%m %H:%M", time.localtime(t)) if t else None


class Caixa:
    """Estado de um self-checkout. Toda escrita passa por `lock`."""

    def __init__(self, pdv, host, max_itens=30, padroes_falha=None,
                 vales=None):
        self.pdv = pdv
        self.host = host
        self.max_itens = max_itens
        self.padroes_falha = padroes_falha or FALHAS_PADRAO
        self.vales = set(normaliza_midia(v) for v in
                         (VALES_PADRAO if vales is None else vales))
        # Categoria da falha lida no visor ("impressora"), NUNCA o texto.
        self.falha = None
        self.falha_em = None
        # Papel da impressora, do status estruturado: None (nunca lido),
        # "ok", "baixo" ou "sem".
        self.papel = None
        self.papel_em = None       # quando o valor MUDOU (para o "assim ha X")
        self.papel_visto_em = None  # quando foi LIDO pela ultima vez
        self.lock = threading.Lock()
        self.estado = None          # "AUTH", "SALE", ...
        self.codigo = None          # 68, 1, ...
        self.mudou_em = None        # ultimo bloco DIFERENTE do anterior
        self.visto_em = None        # ultima linha recebida, qualquer que seja
        self.chamando_desde = None
        self.chamado_rotina = False  # chamado previsivel (bebida): nasce ambar
        self.assinatura = None      # hash do bloco; o texto nunca fica
        self.volume = None
        self.volume_em = None
        self.erro = None            # ultima falha de conexao, para a tela contar
        # TERCEIRO relogio, aprendido em producao em 03/09: a sessao SSH esta
        # viva? Nem toda tela reescreve a cada segundo -- SCREENSV e CLOSED
        # sim (vi CLOSED repetido 82.380 vezes), mas SUB_MSGS e escrito e
        # para. Sem separar "nao chega linha" de "nao chega conexao", uma
        # tela estatica vira falso "sem sinal", e uma maquina travada some
        # dentro do mesmo aviso.
        self.conectado = False
        self.conectado_em = None
        # A cesta da sessao ATUAL, do mais recente para o mais antigo:
        # [descricao, quantidade, momento_da_ultima_leitura].
        #
        # 🔴 MUDANCA DE ESCOPO CONSCIENTE (07/09, pedido do Valmir): ate aqui o
        # painel guardava SO o ultimo item, uma string sobrescrita a cada
        # leitura, e o comentario antigo dizia com todas as letras que a cesta
        # nao existia em lugar nenhum. Agora ela existe -- em memoria, limitada
        # a `max_itens`, e some por inteiro no fim da sessao pelo MESMO caminho
        # que apagava o item unico (ESTADOS_FIM_DE_SESSAO). O que NAO mudou:
        # nada disso vai para disco, para log ou para fora da rede, e valor de
        # compra continua sem existir no codigo. A lista morre com o cliente
        # que a gerou.
        self.itens = []
        # Quantas leituras entraram nesta sessao. NAO e o total da compra: e o
        # que o catalogo conseguiu resolver. Codigo que nao esta no PLU (item
        # de balanca, matricula) nunca chegou aqui e nao e contado.
        self.itens_lidos = 0
        # Bebida alcoolica x vale. Vivem e morrem junto com a cesta.
        self.alcool = []            # descricoes dos itens alcoolicos da sessao
        self.midia = None           # ultima finalizadora escolhida na sessao
        self.midia_em = None
        self.alcool_vale_em = None  # quando o alerta acendeu
        # Congelado pela fiscal (botao Congelar Self). NAO some no fim de
        # sessao: congelado, o visor nem chega a mudar.
        self.congelado_em = None
        self.congelado_por = None

    def aplica(self, estado, codigo, corpo):
        # `corpo` entra so para virar hash e ETIQUETA DE FALHA, e e descartado
        # na saida do metodo. Nenhum dos dois carrega o texto: o hash e
        # irreversivel e a etiqueta e uma palavra de um vocabulario fechado.
        assina = hashlib.sha1(
            (estado + "|" + corpo).encode("utf-8", "replace")
        ).hexdigest()
        falha = classifica_falha(corpo, self.padroes_falha)
        t = agora()
        with self.lock:
            self.visto_em = t
            self.erro = None
            if assina != self.assinatura:
                self.assinatura = assina
                self.mudou_em = t
            self.estado = estado
            self.codigo = codigo
            # O relogio da falha comeca no PRIMEIRO bloco que a mostrou e nao
            # e reiniciado enquanto ela continuar: a maquina reescreve a mesma
            # mensagem varias vezes por segundo, e sem isto o "ha X min" nunca
            # sairia de zero -- justo o numero que diz se alguem ja foi la.
            if falha:
                if self.falha != falha or self.falha_em is None:
                    self.falha_em = t
            else:
                self.falha_em = None
            self.falha = falha
            if e_chamado(estado, codigo):
                if self.chamando_desde is None:
                    self.chamando_desde = t
                self.chamado_rotina = (estado, codigo) in CHAMADO_ROTINA
            else:
                self.chamando_desde = None
                self.chamado_rotina = False
            # A sessao acabou: a cesta do cliente anterior morre aqui, inteira.
            if estado in ESTADOS_FIM_DE_SESSAO:
                self.itens = []
                self.itens_lidos = 0
                self.alcool = []
                self.midia = None
                self.midia_em = None
                self.alcool_vale_em = None

    def marca_erro(self, msg):
        with self.lock:
            self.erro = msg
            self.conectado = False

    def registra_item(self, descricao, alcool=False):
        with self.lock:
            t = agora()
            self.itens_lidos += 1
            if alcool and descricao not in self.alcool:
                self.alcool.append(descricao)
                self._confere_vale(t)
            # Repeticao EM SEQUENCIA vira quantidade em vez de virar linha
            # nova: tres iogurtes iguais ocupariam a lista inteira e
            # empurrariam para fora justamente o que o fiscal ainda nao viu.
            # So o topo e comparado -- item repetido depois de outro continua
            # sendo uma linha propria, porque a ordem de passagem e informacao.
            if self.itens and self.itens[0][0] == descricao:
                self.itens[0][1] += 1
                self.itens[0][2] = t
            else:
                self.itens.insert(0, [descricao, 1, t])
                del self.itens[self.max_itens:]

    def define_midia(self, nome):
        """Finalizadora que o cliente acabou de tocar (`iCMD_Media check value`).

        Trocar de finalizadora APAGA o alerta: se o cliente voltou do vale e
        escolheu credito, nao ha mais nada a impedir. Voltar ao vale acende de
        novo.
        """
        with self.lock:
            t = agora()
            self.midia = (nome or "").strip() or None
            self.midia_em = t
            self._confere_vale(t)

    def _confere_vale(self, t):
        # Chamado com o `lock` ja seguro.
        ativo = (bool(self.alcool) and self.midia is not None
                 and normaliza_midia(self.midia) in self.vales)
        if ativo and self.alcool_vale_em is None:
            self.alcool_vale_em = t
            # Contagem, nao nome de produto: o log sobrevive ao cliente.
            sys.stderr.write("ALCOOL NO VALE pdv=%s finalizadora=%s itens=%d\n"
                             % (self.pdv, self.midia, len(self.alcool)))
        elif not ativo:
            self.alcool_vale_em = None

    def define_papel(self, baixo, sem):
        """Status do papel vindo do `gstTicketStatus` do venditor.

        O relogio so reinicia quando o estado MUDA: a maquina reconsulta a
        impressora varias vezes por venda, e sem isso o "assim ha X min" nunca
        sairia de zero -- justo o numero que diz se alguem ja foi trocar.
        """
        novo = "sem" if sem else ("baixo" if baixo else "ok")
        with self.lock:
            self.papel_visto_em = agora()
            if novo != self.papel:
                self.papel = novo
                self.papel_em = self.papel_visto_em

    def define_item(self, descricao, qtd):
        """Item cuja quantidade vem PRONTA da maquina, nao de contar leituras.

        Hoje so a sacola: o `qty-bag` reimprime o valor corrente a cada aperto
        de +/-, entao somar daria 1, 2, 3 para uma sacola so. Aqui a quantidade
        e FIXADA, o que torna o metodo idempotente -- ver o mesmo valor de novo
        nao muda nada, e por isso a repeticao no log e inofensiva.

        `qtd` zero remove: e assim que a maquina diz que o cliente desistiu da
        sacola depois de ter pedido.
        """
        with self.lock:
            t = agora()
            achou = False
            for i, linha in enumerate(self.itens):
                if linha[0] == descricao:
                    if linha[1] == qtd:
                        return              # nada mudou, nem mexe na ordem
                    self.itens_lidos += qtd - linha[1]
                    del self.itens[i]
                    achou = True
                    break
            if not achou:
                if qtd <= 0:
                    return
                self.itens_lidos += qtd
            if qtd > 0:
                self.itens.insert(0, [descricao, qtd, t])
                del self.itens[self.max_itens:]

    def marca_conectado(self):
        with self.lock:
            self.conectado = True
            self.conectado_em = agora()
            self.erro = None

    def instantaneo(self, limiar_sem_sinal, limiar_alerta, limiar_parado,
                    porta_console=None, limiar_rotina=25, limiar_papel=300):
        with self.lock:
            t = agora()
            visto = self.visto_em
            idade = None if visto is None else t - visto

            # Sem conexao = cego de verdade: nao sabemos nada da maquina.
            cego = not self.conectado

            # Conectado e sem linha nova por muito tempo = a TELA parou. A
            # maquina responde, mas o visor nao muda -- foi assim que o 224
            # apareceu preso em "Reducao pendente / TECLE ENTRA" em 03/09,
            # esperando alguem apertar Enter.
            #
            # O relogio de referencia e a ULTIMA LINHA ou, se nunca chegou
            # nenhuma, o momento da CONEXAO. Sem essa segunda opcao, uma
            # maquina que ja estava congelada quando o coletor subiu ficaria
            # para sempre em "sem sinal": o `tail -n 0` so mostra o que vier
            # DEPOIS, e de uma tela parada nunca vem nada.
            desde = visto if visto is not None else self.conectado_em
            quieto = None if desde is None else t - desde
            parado = (not cego) and quieto is not None and quieto > limiar_parado

            espera = None
            if self.chamando_desde is not None and not cego:
                espera = t - self.chamando_desde

            # Duas fontes independentes de falha da impressora, e nenhuma
            # cobre a outra:
            #   - o VISOR pega "nao responde" (cabo solto, desligada), porque a
            #     maquina reclama quando ela nao responde;
            #   - o STATUS pega papel, que o visor nao conta -- com a bobina
            #     fora a maquina vende calada.
            # Papel fora ganha do "nao responde" na hora de rotular: e a causa
            # mais especifica, e diz o que fazer (trocar a bobina).
            # 🔴 A LEITURA DO PAPEL ENVELHECE, e por isso a afirmacao tambem.
            #
            # O venditor so consulta a impressora em certos momentos da venda.
            # Medido em 09/09: o Valmir trocou a bobina e a maquina passou SEIS
            # MINUTOS sem escrever um unico status -- o painel ficou gritando
            # "sem papel" sobre uma impressora ja consertada. Vermelho que nao
            # sabe se apagar e pior que nao ter alerta: ensina o fiscal a
            # ignorar vermelho, e ai o alarme que importa morre junto.
            #
            # Passado `limiar_papel` sem leitura nova, "sem papel" deixa de ser
            # alarme e vira o que realmente e: a ULTIMA COISA QUE SE SOUBE, com
            # a idade na tela. A verdade volta sozinha na proxima venda, que e
            # quando a maquina consulta de novo.
            papel_fresco = (self.papel_visto_em is not None
                            and t - self.papel_visto_em <= limiar_papel)
            sem_papel = self.papel == "sem" and papel_fresco

            falha_agora = "sem_papel" if sem_papel else self.falha
            falha_em = self.papel_em if sem_papel else self.falha_em

            # Passado CONGELA_MAX a maquina ja soltou sozinha.
            congelado = (self.congelado_em is not None
                         and t - self.congelado_em < CONGELA_MAX)
            if cego:
                modo = "semsinal"
            elif congelado:
                # Acima dos alertas: com o venditor pausado o visor para de
                # escrever, e o que estiver aceso e LEMBRANCA de antes do
                # congelamento. A fiscal ja sabe deste caixa -- foi ela.
                modo = "congelado"
            elif self.alcool_vale_em is not None:
                # ACIMA de tudo que nao seja cegueira. E o unico alarme com
                # prazo de segundos: entre o toque no vale e o cartao aprovado
                # passam poucos segundos, e depois disso nao ha o que impedir.
                # Impressora e chamado esperam; isto nao.
                modo = "alcool_vale"
            elif falha_agora:
                # ACIMA do chamado, de proposito. Um AUTH e um evento de tres
                # segundos numa venda que esta andando; impressora morta trava
                # o caixa inteiro e nao sai sozinho -- ninguem termina compra
                # sem cupom. E a acao e outra: nao e autorizar, e por papel ou
                # chamar a TI. Na pratica os dois nao competem, porque com a
                # falha no visor o estado nem chega a virar AUTH.
                modo = "falha"
            elif espera is not None and espera >= limiar_alerta:
                # Chamado de rotina segura o vermelho ate o limiar de rotina.
                # Passou disso, ninguem foi: vira alarme como qualquer outro.
                if self.chamado_rotina and espera < limiar_rotina:
                    modo = "aguardando"
                else:
                    modo = "chamando"
            elif parado:
                modo = "parado"
            elif self.estado in ESTADOS_INATIVOS:
                modo = "inativo"
            else:
                modo = "tranquilo"

            return {
                "pdv": self.pdv,
                "modo": modo,
                "estado": self.estado,
                "codigo": self.codigo,
                # segundos, nao timestamps: o relogio do tablet nao precisa
                # bater com o do servidor
                "mudou_ha": None if self.mudou_em is None else round(t - self.mudou_em, 1),
                "visto_ha": None if idade is None else round(idade, 1),
                "espera": None if espera is None else round(espera, 1),
                "volume": self.volume,
                "volume_ha": None if self.volume_em is None else round(t - self.volume_em, 1),
                "conectado": self.conectado,
                # 🔴 O item SO sai daqui durante a intervencao. Em caixa verde ou
                # laranja o campo nem existe na resposta -- a cesta do cliente
                # nao trafega. A regra mora no servidor, nao na tela: se um dia
                # alguem escrever outro front-end, ele nao consegue pedir o que
                # a API nao entrega.
                # Diagnostico: diz SE ha item capturado, nunca QUAL. Serve para
                # saber se o coletor de itens esta vivo sem precisar esperar uma
                # intervencao -- e sem que a cesta trafegue. Que a maquina esta
                # em uso ja e visivel de longe; o que ela vende, nao.
                # Console de supervisor NATIVO do venditor (umbra), servido pela
                # propria maquina. E so um endereco: quem libera o caixa e ela,
                # entrando com o login dela la dentro. O painel abre a porta e
                # nao executa nada -- toque sem querer nao libera peso nenhum, e
                # a trilha de auditoria continua registrando QUEM autorizou.
                # Nao reimplementamos o protocolo de proposito: o console e
                # artefato do fornecedor e sobrevive a atualizacao; engenharia
                # reversa quebraria na primeira.
                "console": (None if not porta_console
                            else "http://%s:%d/" % (self.host, porta_console)),
                "tem_item": bool(self.itens),
                # Rodolfo pediu o item tambem durante a venda (celula ambar), nao
                # so na intervencao. O limite deixa de ser "so no alerta" e passa
                # a ser "so enquanto AQUELE cliente esta no caixa" -- e continua
                # sendo garantido no servidor, porque a cesta e apagada ao
                # entrar em SCREENSV/IDLE/HELLO/THANKYOU/CLOSED/Z. Fora de uma
                # sessao ele ja e nulo, entao expor aqui nao alarga nada alem
                # disso. Valor de compra continua nunca saindo.
                "rotina": self.chamado_rotina,
                # `item` continua existindo e continua sendo o mais recente:
                # e o campo que a versao anterior do painel le, e um tablet com
                # a pagina velha em cache nao pode ficar sem item so porque o
                # servidor subiu primeiro.
                "item": self.itens[0][0] if self.itens else None,
                "item_ha": (round(t - self.itens[0][2], 1)
                            if self.itens else None),
                # A cesta da sessao, mais recente primeiro. Chaves curtas
                # porque isto viaja a cada 500 ms, quatro caixas por vez.
                #   d = descricao   q = quantidade   ha = segundos desde a leitura
                "itens": [
                    {"d": d, "q": q, "ha": round(t - m, 1)}
                    for d, q, m in self.itens
                ],
                "itens_lidos": self.itens_lidos,
                "congelado": ({"por": self.congelado_por,
                               "ha": round(t - self.congelado_em, 1),
                               "resta": round(CONGELA_MAX - (t - self.congelado_em), 1)}
                              if congelado else None),
                # So existe com o alerta aceso. Leva a finalizadora e QUAIS
                # itens sao alcoolicos -- a fiscal chega sabendo o que tirar.
                "alcool_vale": ({"midia": self.midia,
                                 "itens": list(self.alcool),
                                 "ha": round(t - self.alcool_vale_em, 1)}
                                if self.alcool_vale_em is not None else None),
                # A CATEGORIA da falha, nunca a mensagem. Vocabulario fechado:
                # hoje so "impressora".
                "falha": falha_agora,
                "falha_ha": round(t - falha_em, 1) if falha_em else None,
                # Papel acabando NAO e falha: a maquina ainda vende. Vai como
                # aviso discreto, para alguem trocar a bobina antes de o caixa
                # parar. "ok" e "sem" nao viram aviso -- o primeiro nao e
                # noticia e o segundo ja acendeu a celula inteira.
                # O estado CRU do papel, para diagnostico. Sem ele "tem
                # papel" e "nunca li o papel" chegavam os dois como silencio, e
                # em 10/09 isso me custou uma ida ao log da maquina para
                # responder por que o painel estava calado. Depois de um
                # restart do coletor todo caixa comeca em `null` -- desconhecido
                # nao e o mesmo que ok, e a API passa a dizer isso.
                #   null = nunca lido | "ok" | "baixo" | "sem"
                "papel": self.papel,
                "papel_ha": (round(t - self.papel_visto_em, 1)
                             if self.papel_visto_em else None),
                "papel_baixo": self.papel == "baixo" and papel_fresco,
                # "sem papel" que ja envelheceu: nao grita mais, mas continua
                # sendo dito, com a idade. A tela nao esconde o que sabe -- so
                # para de afirmar como se fosse agora.
                "papel_velho_ha": (round(t - self.papel_visto_em, 1)
                                   if (self.papel == "sem" and not papel_fresco
                                       and self.papel_visto_em) else None),
                "erro": self.erro,
            }


class Coletor(threading.Thread):
    """Um `tail -F` por maquina. Cai, avisa, e volta a tentar."""

    daemon = True

    def __init__(self, caixa, cfg):
        super().__init__(name="coletor-%s" % caixa.pdv)
        self.caixa = caixa
        self.cfg = cfg
        self.parar = threading.Event()

    def comando(self):
        c = self.cfg
        base = [
            "ssh", "-T",
            "-o", "BatchMode=yes",
            "-o", "StrictHostKeyChecking=" + c.get("strict_host_key", "yes"),
            "-o", "ServerAliveInterval=10",
            "-o", "ServerAliveCountMax=2",
            "-o", "ConnectTimeout=10",
        ]
        if c.get("known_hosts"):
            base += ["-o", "UserKnownHostsFile=" + c["known_hosts"]]
        if c.get("chave"):
            base += ["-i", c["chave"]]
        base.append("%s@%s" % (c.get("usuario", "monitorfiscal"), self.caixa.host))
        # Do outro lado a chave esta presa a `command=`, entao este argumento e
        # so o seletor do que o script ja permite. Ver docs/pedido-ti.md.
        base.append(c.get("cmd_log", "log-seguir"))
        return base

    def run(self):
        espera_reconexao = 2
        while not self.parar.is_set():
            proc = None
            try:
                # Modo TEXTO com encoding explicito, nao binario.
                # Em modo binario o Python IGNORA bufsize=1 e usa buffer de
                # bloco: como o self-checkout escreve ~120 bytes por segundo,
                # um buffer de 8 KB seguraria mais de um MINUTO de log antes
                # de entregar a primeira linha. O painel ficaria atrasado sem
                # dar sinal disso. Texto + latin-1 restaura o buffer por linha
                # e ainda decodifica certo -- o log NAO e UTF-8.
                proc = subprocess.Popen(
                    self.comando(),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    bufsize=1,
                    universal_newlines=True,
                    encoding="latin-1",
                    errors="replace",
                )
                espera_reconexao = 2
                self.caixa.marca_conectado()
                estado = codigo = None
                sobra = []
                for cru in proc.stdout:
                    if self.parar.is_set():
                        break
                    linha = cru.rstrip("\r\n")
                    m = CABECALHO.match(linha)
                    if m:
                        # bloco anterior fecha aqui
                        if estado is not None:
                            self.caixa.aplica(estado, codigo, "\n".join(sobra))
                        nome = NOME_ESTADO.match(m.group("estado"))
                        estado = nome.group(1) if nome else m.group("estado")
                        codigo = int(nome.group(2)) if nome and nome.group(2) else None
                        sobra = []
                    elif estado is not None:
                        sobra.append(linha)
                        if len(sobra) >= 2:
                            self.caixa.aplica(estado, codigo, "\n".join(sobra))
                            estado = None
                            sobra = []
                erro = (proc.stderr.read() or "").strip()
                self.caixa.marca_erro(erro[:200] or "conexão encerrada")
            except Exception as e:                        # noqa: BLE001
                self.caixa.marca_erro("%s: %s" % (type(e).__name__, e))
            finally:
                if proc is not None:
                    try:
                        proc.kill()
                    except Exception:                     # noqa: BLE001
                        pass
            # Reconecta com recuo, mas nunca fica calado: o `visto_em` para de
            # avancar e a tela mostra "sem sinal" sozinha.
            self.parar.wait(espera_reconexao)
            espera_reconexao = min(espera_reconexao * 2, 30)


class Catalogo:
    """SKU -> descricao, lido do PLU da propria maquina.

    Serve para DUAS coisas, e a segunda e a que importa:
      1. traduzir 7891991001342 em "GUARANA ANTARCTICA 2L", que e o que o
         fiscal precisa ler;
      2. FILTRAR. So chega a tela o numero que existe como SKU. E assim que a
         matricula da fiscal -- que trafega pelo mesmo canal e com o mesmo
         formato do codigo de barras -- nunca vira "item" no painel.

    Medido no parque em 03/09: 46.459 itens, extraidos em 0,12 s, carga 0,00.
    """

    def __init__(self, cfg):
        self.cfg = cfg
        self.mapa = {}
        self.carregado_em = None
        self.cache = cfg.get("cache_plu",
                             os.path.join(AQUI, "..", "plu-cache.tsv"))
        self.validade = cfg.get("plu_validade_h", 12) * 3600
        # Recarga que volta com menos que isto do mapa atual NAO entra. O
        # PLU.xml tem 96 MB e a carga da retaguarda chega em horario comercial
        # (vista as 09:32 e as 17:41): ler o arquivo no meio da gravacao da uma
        # lista pela metade, com codigo de saida 0. Aceitar isso tiraria
        # milhares de produtos do painel -- em silencio, ate a proxima recarga.
        self.minimo_recarga = cfg.get("plu_minimo_recarga", 0.8)
        # SKUs de bebida alcoolica, pelo NCM -- ver NCM_ALCOOL_PADRAO.
        self.alcool = set()
        self.ncm_alcool = tuple(str(x) for x in
                                cfg.get("ncm_alcool", NCM_ALCOOL_PADRAO))
        self.alcool_incluir = set(str(x) for x in cfg.get("alcool_incluir") or [])
        self.alcool_excluir = set(str(x) for x in cfg.get("alcool_excluir") or [])

    def _monta(self, linhas):
        """(mapa, alcool) a partir de "<sku>\\t<desc>[\\t<ncm>]".

        Aceita as DUAS formas: o `plu-mapa` de duas colunas (PDV ainda sem o
        seletor novo, ou cache antigo) so nao traz alcool nenhum.
        """
        mapa, alcool = {}, set()
        for ln in linhas:
            partes = ln.rstrip("\r\n").split("\t")
            if len(partes) < 2:
                continue
            sku, desc = partes[0], partes[1].strip()
            if not (sku and desc):
                continue
            mapa[sku] = desc
            ncm = partes[2].strip() if len(partes) > 2 else ""
            if sku in self.alcool_incluir or (
                    ncm and ncm.startswith(self.ncm_alcool)
                    and sku not in self.alcool_excluir):
                alcool.add(sku)
        return mapa, alcool

    def _abre(self, caminho):
        with open(caminho, encoding="latin-1") as fh:
            return self._monta(fh)

    def _le_arquivo(self, caminho):
        return self._abre(caminho)[0]

    def _le_texto(self, texto):
        return self._monta(texto.splitlines())[0]

    def e_alcool(self, sku):
        return sku in self.alcool

    def _busca(self, host):
        """O PLU de uma maquina: primeiro com NCM, depois o formato antigo.

        PDV que ainda nao tem o `plu-mapa-ncm` responde "comando nao
        permitido" -- a cesta continua funcionando, so sem o alerta de alcool.
        """
        cmds = [self.cfg.get("cmd_plu", "plu-mapa-ncm")]
        if "plu-mapa" not in cmds:
            cmds.append("plu-mapa")
        ok, saida = False, ""
        for cmd in cmds:
            ok, saida = ssh_curto(self.cfg, host, cmd, timeout=90)
            if ok and saida:
                return True, saida
        return ok, saida

    def recarrega(self, hosts, extras=None):
        """Busca o PLU de novo, SEM olhar o cache. Devolve (ok, itens, motivo).

        O mapa novo e montado inteiro por fora e entra numa atribuicao so: quem
        esta consultando `descreve` agora ve o mapa velho ou o novo, nunca um
        pela metade. Se nada der certo, o mapa de antes continua valendo.
        """
        antes = len(self.mapa)
        motivo = "nenhum PDV respondeu"
        for host in hosts:
            ok, saida = self._busca(host)
            if not ok or not saida:
                motivo = "%s: %s" % (host, (saida or "saida vazia")[:80])
                continue
            novo, alcool = self._monta(saida.splitlines())
            if antes and len(novo) < antes * self.minimo_recarga:
                # Provavel PLU.xml sendo gravado nesta maquina. Outra pode ja
                # ter terminado -- o PLU e o mesmo no parque.
                motivo = "%s: veio com %d itens, o atual tem %d" % (
                    host, len(novo), antes)
                continue
            for cod, nome in (extras or {}).items():
                novo[cod] = nome          # config manda -- ver Servico.inicia
            self.alcool = alcool
            self.mapa = novo
            self.carregado_em = agora()
            self._grava_cache(saida)
            return True, len(novo), ""
        return False, antes, motivo

    def _grava_cache(self, texto):
        try:
            tmp = self.cache + ".novo"
            with open(tmp, "w", encoding="latin-1") as fh:
                fh.write(texto + "\n")
            try:
                os.replace(tmp, self.cache)
            except OSError:
                # No container o cache e bind mount de ARQUIVO, e rename por
                # cima de ponto de montagem da EBUSY. Ai grava no lugar.
                with open(self.cache, "w", encoding="latin-1") as fh:
                    fh.write(texto + "\n")
                os.remove(tmp)
        except Exception:                                  # noqa: BLE001
            pass   # cache e so atalho para a partida; o mapa ja esta em memoria

    def carrega(self, hosts):
        # Cache recente serve: o PLU muda uma vez por dia.
        try:
            if os.path.isfile(self.cache):
                idade = agora() - os.path.getmtime(self.cache)
                if idade < self.validade:
                    self.mapa, self.alcool = self._abre(self.cache)
                    self.carregado_em = agora()
                    return len(self.mapa)
        except Exception:                                  # noqa: BLE001
            pass

        # Qualquer maquina serve: o PLU e o mesmo no parque. A primeira que
        # responder resolve.
        for host in hosts:
            ok, saida = self._busca(host)
            if not ok or not saida:
                continue
            try:
                with open(self.cache, "w", encoding="latin-1") as fh:
                    fh.write(saida)
                self.mapa, self.alcool = self._abre(self.cache)
                self.carregado_em = agora()
                return len(self.mapa)
            except Exception:                              # noqa: BLE001
                continue
        return 0

    def descreve(self, sku):
        # Caminho normal: o codigo de barras E o SKU.
        d = self.mapa.get(sku)
        if d:
            return d

        # Caminho da BALANCA. O que o scanner le num item pesado nao e um SKU:
        # e uma etiqueta que embute o PRECO, entao o numero inteiro nunca esta
        # no PLU e o item sumia do painel. Medido ao vivo nos quatro caixas em
        # 07/09: 4 de 7 leituras (57%) caiam aqui -- hortifruti, padaria,
        # acougue e frios, uma fatia enorme da cesta, invisivel.
        m = BALANCA.match(sku)
        if not m:
            return None
        # Leitura FIXA das posicoes 2 a 5, confirmada pelo Valmir: o cadastro
        # de balanca da loja usa PLU de 4 digitos.
        #
        # 🔴 NAO tentar "o prefixo mais longo que existir no PLU". Testei, e
        # produz nome ERRADO: 2118600002541 casaria com o PLU 11860 =
        # "ESPONJA BANHO BUZATO" quando o item e o PLU 1186 = "CEBOLA COMUM
        # KG". Num painel fiscal nome errado e pior que nome nenhum.
        #
        # O `00` obrigatorio no meio (ver BALANCA) e a trava estrutural: e o
        # resto do campo de codigo, de 6 digitos, que sobra depois do PLU de 4.
        # Sem ele qualquer EAN comecado em 2 viraria um item inventado.
        # Leitura EXATA dos 4 digitos, e mais nada.
        #
        # Cheguei a por aqui um tratamento para PLU de menos de 4 digitos, com
        # `lstrip`/`rstrip` e uma trava de ambiguidade. Estava ERRADO e foi
        # removido: os codigos curtos do cadastro (26 MELANCIA UN, 213 ABACAXI
        # PEROLA UN) sao EAN de item vendido POR UNIDADE, nao PLU de balanca --
        # nunca entram numa etiqueta pesada. O que a trava fazia de fato era
        # descartar 16 codigos de 4 digitos legitimos, 13 deles PESADOS: 1220
        # CAR SUIN PERNIL KG, 2130 BACON PRIETO EXTRA, 3410 MEXERICA DEKOPON
        # KG, 1580 QUEIJO FRESCAL KG... exatamente os itens que a decodificacao
        # existe para recuperar.
        #
        # No cadastro (coluna "GTIN/PLU Principal" do ERP) esse campo de 4
        # digitos e o codigo que vai para o PDV, tanto em UN quanto em KG. Se o
        # numero nao estiver la, nao ha o que mostrar -- e o item e descartado
        # em silencio, como sempre foi.
        return self.mapa.get(m.group(1))


def ssh_curto(cfg, host, argumento, timeout=15):
    """Uma chamada SSH pontual (volume). Devolve (ok, saida)."""
    cmd = [
        "ssh", "-T",
        "-o", "BatchMode=yes",
        "-o", "StrictHostKeyChecking=" + cfg.get("strict_host_key", "yes"),
        "-o", "ConnectTimeout=10",
    ]
    if cfg.get("known_hosts"):
        cmd += ["-o", "UserKnownHostsFile=" + cfg["known_hosts"]]
    if cfg.get("chave"):
        cmd += ["-i", cfg["chave"]]
    cmd.append("%s@%s" % (cfg.get("usuario", "monitorfiscal"), host))
    cmd.append(argumento)
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=timeout)
        saida = r.stdout.decode("latin-1", "replace").strip()
        if r.returncode != 0:
            return False, (r.stderr.decode("latin-1", "replace").strip() or "erro")[:200]
        return True, saida
    except subprocess.TimeoutExpired:
        return False, "tempo esgotado"
    except Exception as e:                                # noqa: BLE001
        return False, "%s: %s" % (type(e).__name__, e)


def proxima_recarga(hora, t):
    """Instante (epoch) do proximo HH:MM local estritamente depois de `t`.

    Hora invalida na config vira 06:00 -- config errada nao pode matar a thread
    e deixar o catalogo congelado sem ninguem saber.
    """
    try:
        hh, mm = [int(x) for x in str(hora).split(":")]
        if not (0 <= hh < 24 and 0 <= mm < 60):
            raise ValueError(hora)
    except (ValueError, TypeError):
        hh, mm = 6, 0
    lt = time.localtime(t)
    alvo = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, hh, mm, 0, 0, 0, -1))
    if alvo <= t:
        # mktime normaliza o dia 32 para o dia 1 do mes seguinte
        alvo = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday + 1,
                            hh, mm, 0, 0, 0, -1))
    return alvo


class RecargaCatalogo(threading.Thread):
    """Recarrega o catalogo PLU uma vez por dia, em `plu_recarga_hora`.

    Antes o catalogo so era lido na partida: produto cadastrado depois disso
    nao aparecia no painel ate alguem reiniciar o monitor -- e o monitor chegou
    a ficar 3 dias no ar com a lista do dia em que subiu.

    Se a recarga falhar, tenta de novo a cada `plu_nova_tentativa_min` ate
    dar certo, e so entao volta ao horario diario.
    """
    daemon = True

    def __init__(self, servico, primeira_ok=True):
        threading.Thread.__init__(self, name="recarga-plu")
        self.servico = servico
        self.hora = servico.cfg.get("plu_recarga_hora", "06:00")
        self.nova_tentativa = servico.cfg.get("plu_nova_tentativa_min", 30) * 60
        # Partida sem catalogo nao espera ate amanha.
        self.proxima = (proxima_recarga(self.hora, agora()) if primeira_ok
                        else agora() + self.nova_tentativa)

    def run(self):
        while True:
            falta = self.proxima - agora()
            if falta > 0:
                # Passos curtos: relogio acertado (NTP, fuso) nao faz perder o
                # dia inteiro.
                time.sleep(min(60, falta))
                continue
            try:
                ok = self.servico.recarrega_catalogo()
            except Exception as e:                         # noqa: BLE001
                sys.stderr.write("AVISO: recarga do catálogo PLU quebrou: %s\n" % e)
                ok = False
            self.proxima = (proxima_recarga(self.hora, agora()) if ok
                            else agora() + self.nova_tentativa)


class ColetorItens(Coletor):
    """Segue o venditor.log e monta a cesta da sessao em andamento.

    Herda a maquinaria de conexao e reconexao do Coletor; muda o comando e o
    que faz com cada linha.
    """

    def __init__(self, caixa, cfg, catalogo):
        super().__init__(caixa, cfg)
        self.name = "itens-%s" % caixa.pdv
        self.catalogo = catalogo
        # Codigos das sacolas, na ordem dos BAG_QTY, como a maquina anunciou no
        # ultimo `--list-items`. Vazio ate a primeira oferta de sacola.
        self.sacolas = []
        # A ultima invocacao do qty-bag foi uma MUDANCA (`--oper-math`)? So
        # nesse caso o BAG_QTY seguinte vale. Ver o comentario no `run`.
        self.sacola_mudanca = False

    def nome_sacola(self, indice):
        """Rotulo do tipo de sacola `indice` (0-based, = BAG_QTY1, BAG_QTY2...).

        Os codigos que a maquina passa em `--list-items` nao estao no PLU
        exportado desta loja, entao o catalogo nao resolve. `nomes_sacola` na
        config existe para o TI dizer qual e qual; sem ela, o rotulo generico,
        que ja e a informacao que o fiscal precisa (levou sacola, e quantas).
        """
        cod = self.sacolas[indice] if 0 <= indice < len(self.sacolas) else None
        if cod:
            d = (self.cfg.get("nomes_sacola") or {}).get(cod)
            if d:
                return d
            d = self.catalogo.descreve(cod)
            if d:
                return d
        return "SACOLA" if indice == 0 else "SACOLA TIPO %d" % (indice + 1)

    def processa(self, linha):
        """Uma linha do venditor.log. Fora do `run` para o teste poder
        alimentar as linhas gravadas nos caixas sem SSH."""
        # --- status do PAPEL, do gstTicketStatus ---
        # Vem antes de tudo: e uma linha propria, sem `data=[]` e
        # sem `qty-bag`, entao nao disputa com os outros canais.
        m = STATUS_PAPEL.search(linha)
        if m:
            self.caixa.define_papel(m.group(1) == "1",
                                    m.group(2) == "1")
            return

        # --- canal da SACOLA, que nao passa por `data=[...]` ---
        #
        # So a linha `try [...]` conta como invocacao. O eco dos
        # argumentos (` 1: [--command=qty-bag]`) vem logo depois e
        # tambem carrega o nome do comando -- se ele entrasse aqui,
        # apagaria o `--oper-math` que a linha anterior acabou de
        # marcar, e nenhuma mudanca de sacola seria aplicada.
        if "try [" in linha and "--command=qty-bag" in linha:
            m = SACOLA_LISTA.search(linha)
            if m:
                self.sacolas = m.group(1).split(",")
            self.sacola_mudanca = "--oper-math=" in linha
            return
        m = SACOLA_QTD.search(linha)
        if m:
            # 🔴 SO VALE O VALOR QUE VEM DE UMA MUDANCA.
            # Gravado no 223 em 08/09, com o cliente levando uma
            # sacola de cada tipo:
            #   13:35:36 try [qty-bag ...]        <- abre
            #   13:35:36 BAG_QTY1=[0] BAG_QTY2=[0]   inicializacao
            #   13:35:38 try [qty-bag --oper-math=+]
            #   13:35:38 BAG_QTY1=[1]                cinza = 1
            #   13:35:40 try [qty-bag --oper-math=+]
            #   13:35:40 BAG_QTY2=[1]                verde = 1
            #   13:35:43 BAG_QTY1=[0]             <- SEM invocacao
            #   13:35:44 BAG_QTY2=[0]             <- SEM invocacao
            # Os dois zeros do fim sao o dialogo FECHANDO e zerando
            # as variaveis, nao o cliente desistindo -- e eram eles
            # que faziam a sacola aparecer no painel e sumir logo
            # depois. O mesmo padrao no 121 no mesmo dia.
            #
            # Uma invocacao vale por UM valor: o flag e consumido.
            if not self.sacola_mudanca:
                return
            self.sacola_mudanca = False
            # `iOS_ExternalController read [BAG_QTY1=0]` NAO casa:
            # a regex exige os colchetes do valor, e so a linha
            # `BAG_QTY1=[0]` os tem. Sem isso, a mesma mudanca
            # seria processada duas vezes por aperto de botao.
            self.caixa.define_item(
                self.nome_sacola(int(m.group(1)) - 1),
                int(m.group(2)),
            )
            return

        # --- FINALIZADORA tocada pelo cliente ---
        m = MIDIA.search(linha)
        if m:
            self.caixa.define_midia(m.group(1))
            return

        # --- canal normal: codigo lido pelo scanner ---
        m = DADO_LIDO.search(linha)
        if not m:
            return
        desc = self.catalogo.descreve(m.group(1))
        # Numero que nao esta no PLU nao e produto: e matricula,
        # senha ou codigo interno. Sai daqui e nao vai a lugar
        # nenhum -- nem para log, nem para memoria.
        if desc:
            self.caixa.registra_item(
                desc, self.catalogo.e_alcool(m.group(1)))

    def comando(self):
        base = super().comando()
        base[-1] = self.cfg.get("cmd_venditor", "venditor-seguir")
        return base

    def run(self):
        espera = 2
        while not self.parar.is_set():
            proc = None
            try:
                proc = subprocess.Popen(
                    self.comando(),
                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                    bufsize=1, universal_newlines=True,
                    encoding="latin-1", errors="replace",
                )
                espera = 2
                for linha in proc.stdout:
                    if self.parar.is_set():
                        break

                    self.processa(linha)
            except Exception:                              # noqa: BLE001
                pass
            finally:
                if proc is not None:
                    try:
                        proc.kill()
                    except Exception:                      # noqa: BLE001
                        pass
            # Falha aqui NAO deixa a maquina "sem sinal": o item e acessorio,
            # quem manda no diagnostico e o coletor do display.
            self.parar.wait(espera)
            espera = min(espera * 2, 60)


class Servico:
    def __init__(self, cfg):
        self.cfg = cfg
        self.limiar_sem_sinal = cfg.get("limiar_sem_sinal", 15)
        self.limiar_alerta = cfg.get("limiar_alerta", 10)
        # 2 min sem o visor mudar, com a conexao viva. Provisorio: falta medir
        # quantas vezes por dia isso acontece em operacao normal antes de
        # decidir se vira alerta vermelho ou fica so informativo.
        self.limiar_parado = cfg.get("limiar_parado", 120)
        # Porta do console de supervisor do venditor. 0 ou nulo desliga o botao.
        self.porta_console = cfg.get("porta_console", 8606)
        # Segundos que um chamado de ROTINA fica ambar antes de virar vermelho.
        self.limiar_rotina = cfg.get("limiar_rotina", 25)
        # Quanto tempo uma leitura de papel continua valendo como afirmacao.
        # 300 s com folga: durante uma venda a maquina consulta a impressora
        # varias vezes, e o maior intervalo medido entre consultas foi ~2,7 min.
        self.limiar_papel = cfg.get("limiar_papel", 300)
        # Segundos que a MESMA acao no MESMO caixa fica recusada. Toque duplo
        # em tablet e regra, nao excecao -- e dois reboots seguidos derrubam a
        # maquina duas vezes.
        self.intervalo_acao = cfg.get("intervalo_acao", 30)
        self.ultima_acao = {}
        self.lock_acao = threading.Lock()
        # PINs que abrem o painel, cada um com um rotulo para o log.
        # `pin_acoes` aceita tres formatos, e o terceiro e o que vale a pena:
        #     "1207"                        um PIN so
        #     ["1207", "32010"]             varios
        #     {"32010": "Ana", ...}         varios, com NOME
        # Vazio ou ausente desliga a exigencia.
        #
        # Sao cracha de gente, na pratica: a matricula que a pessoa ja usa no
        # caixa. Por isso o rotulo importa -- e com ele que o log consegue
        # dizer QUEM reiniciou um PDV, coisa que antes se perdia porque todo
        # mundo usava o mesmo PIN.
        bruto = cfg.get("pin_acoes") or ""
        self.pins = {}
        if isinstance(bruto, dict):
            self.pins = dict((str(k), str(v)) for k, v in bruto.items() if k)
        elif isinstance(bruto, (list, tuple)):
            self.pins = dict((str(k), str(k)) for k in bruto if k)
        elif bruto:
            self.pins = {str(bruto): str(bruto)}

        # PINs que podem ser DIGITADOS. Os demais so valem passando o cracha
        # no leitor.
        #
        # 🔴 ISTO E REGRA DE OPERACAO, NAO BARREIRA. Quem sabe se veio de
        # leitor ou de dedo e a TELA; o servidor so recebe o que ela afirma, e
        # afirmacao de cliente nao e prova. Serve contra o caso real -- alguem
        # que decorou a matricula da colega e a digita no teclado da tela --
        # e nao contra quem monta a requisicao na mao.
        #
        # A versao que fecha de verdade e o cracha codificar algo que o teclado
        # nao produz (prefixo, sufixo, digito extra). Ai o PIN cadastrado passa
        # a ser a string INTEIRA lida, e digitar a matricula simplesmente nao
        # casa. Depende de saber o que o cracha da loja imprime.
        #
        # Ausente, todos podem ser digitados -- e o comportamento de antes.
        dig = cfg.get("pins_digitaveis")
        self.pins_digitaveis = (set(str(x) for x in dig) if dig is not None
                                else set(self.pins))
        # Sessoes abertas: token -> ultimo uso. O token vive so na memoria do
        # servidor e so na memoria da pagina -- recarregar pede o PIN de novo,
        # que e exatamente o pedido: PIN toda vez que se acessa o endereco.
        self.sessoes = {}
        # Sessao ociosa morre. O painel pergunta a cada 500 ms, entao uma aba
        # aberta se renova sozinha; este prazo so limpa o que ficou para tras.
        self.sessao_validade = cfg.get("sessao_validade", 12 * 3600)
        # Forca bruta: um PIN de 4 digitos sao 10 mil tentativas, e uma rede de
        # loja e rapida. Sem freio, adivinhar leva minutos.
        self.pin_erros = {}
        # Quantos itens da cesta ficam em memoria por caixa. O painel mostra
        # menos que isso (3 em alarme, 5 em venda); a folga existe para o
        # contador "+N anteriores" dizer a verdade sem guardar a compra toda.
        self.max_itens = int(cfg.get("max_itens", 30))
        # Mensagens de falha reconhecidas no visor. Vem da config para o TI
        # poder acrescentar o texto exato que a maquina dele escreve, sem
        # esperar por versao nova do coletor.
        self.padroes_falha = {}
        for cat, marcas in (cfg.get("padroes_falha") or FALHAS_PADRAO).items():
            self.padroes_falha[cat] = [_achatado(m) for m in marcas]
        self.caixas = {}
        for m in cfg["maquinas"]:
            self.caixas[int(m["pdv"])] = Caixa(int(m["pdv"]), m["host"],
                                               self.max_itens,
                                               self.padroes_falha,
                                               cfg.get("finalizadoras_vale"))
        self.catalogo = Catalogo(cfg)
        self.coletores = [Coletor(c, cfg) for c in self.caixas.values()]
        self.coletores_itens = []
        self.recarga = None

    def inicia(self):
        for c in self.coletores:
            c.start()
        # O catalogo tem de existir ANTES do coletor de itens: sem ele nada
        # passa no filtro, e o painel ficaria sem item sem dizer por que.
        n = self.catalogo.carrega([c.host for c in self.caixas.values()])
        # As sacolas NAO vem no PLU exportado -- conferido: nem 7899498703011
        # nem 7898257751348 estao no plu-cache. Enquanto o unico caminho delas
        # era o `qty-bag`, isso nao aparecia; mas em 08/09, gravando o 223, o
        # Valmir bipou 7898257751348 direto no scanner e o item foi descartado
        # em silencio, porque o catalogo nao conhecia o codigo.
        # `nomes_sacola` e a unica fonte que sabe esses nomes, entao ela entra
        # no catalogo e passa a valer para os DOIS caminhos: o botao e o bipe.
        # A CONFIG MANDA, mesmo quando o PLU tambem traz o codigo. Era
        # `setdefault` (cadastro mandava) ate 14/09, quando o plu-mapa passou a
        # ler produto de varios codigos e as duas sacolas apareceram no PLU como
        # "SACOLINHA BIOP.48X55" e "SACOLINHA BIOPLAST" -- sem a cor, que e o
        # que o Valmir corrigiu duas vezes. E o botao (`nome_sacola`) ja dava
        # prioridade a config: a mesma sacola saia com dois nomes.
        extras = self.sacolas()
        for cod, nome in extras.items():
            self.catalogo.mapa[cod] = nome
        sys.stderr.write("Catálogo PLU: %d itens (+%d sacolas da config), "
                         "%d de bebida alcoólica\n"
                         % (n, len(extras), len(self.catalogo.alcool)))
        if n:
            self.liga_itens()
        else:
            sys.stderr.write(
                "AVISO: sem catálogo PLU — o último item não será exibido.\n")
        self.recarga = RecargaCatalogo(self, primeira_ok=bool(n))
        self.recarga.start()

    def sacolas(self):
        return self.cfg.get("nomes_sacola") or {}

    def liga_itens(self):
        # Uma vez so. Tambem e chamado pela recarga: se o monitor subiu sem
        # catalogo, a cesta passa a funcionar quando a lista chegar.
        if self.coletores_itens:
            return
        self.coletores_itens = [
            ColetorItens(c, self.cfg, self.catalogo)
            for c in self.caixas.values()
        ]
        for c in self.coletores_itens:
            c.start()

    def recarrega_catalogo(self):
        hosts = [c.host for c in self.caixas.values()]
        antes = len(self.catalogo.mapa)
        ok, n, motivo = self.catalogo.recarrega(hosts, self.sacolas())
        if ok:
            sys.stderr.write("Catálogo PLU recarregado: %d itens (antes %d)\n"
                             % (n, antes))
            self.liga_itens()
        else:
            sys.stderr.write("AVISO: recarga do catálogo PLU falhou (%s); "
                             "segue a lista anterior, %d itens\n" % (motivo, n))
        return ok

    def estado(self):
        return {
            "gerado_em": round(agora(), 1),
            "limiar_alerta": self.limiar_alerta,
            "limiar_sem_sinal": self.limiar_sem_sinal,
            "limiar_parado": self.limiar_parado,
            "limiar_rotina": self.limiar_rotina,
            "caixas": [
                self.caixas[k].instantaneo(
                    self.limiar_sem_sinal, self.limiar_alerta, self.limiar_parado,
                    self.porta_console, self.limiar_rotina, self.limiar_papel)
                for k in sorted(self.caixas)
            ],
        }

    def volume_ler(self, pdv):
        c = self.caixas.get(pdv)
        if c is None:
            return False, "PDV desconhecido"
        ok, saida = ssh_curto(self.cfg, c.host, self.cfg.get("cmd_vol_ler", "volume-ler"))
        if ok:
            with c.lock:
                c.volume = saida
                c.volume_em = agora()
        return ok, saida

    def volume_definir(self, pdv, valor):
        c = self.caixas.get(pdv)
        if c is None:
            return False, "PDV desconhecido"
        try:
            v = int(valor)
        except (TypeError, ValueError):
            return False, "valor inválido"
        # O piso real e imposto no script dentro da maquina. Este limite aqui e
        # so para nao mandar bobagem pela rede -- a autoridade e o lado de la.
        v = max(0, min(100, v))
        ok, saida = ssh_curto(
            self.cfg, c.host,
            "%s %d" % (self.cfg.get("cmd_vol_definir", "volume-definir"), v),
        )
        if ok:
            # `saida` e o volume REAL lido de volta pelo script, nao o pedido.
            with c.lock:
                c.volume = saida
                c.volume_em = agora()
        return ok, saida

    # ---- acoes na maquina -------------------------------------------------
    #
    # 🔴 ESTE E O PRIMEIRO CAMINHO DO PAINEL QUE MEXE NA MAQUINA. Ate aqui o
    # unico botao que tocava no self-checkout era o "Liberar", e ele NAO
    # executava nada -- abria o console do fornecedor para a fiscal entrar com
    # o login dela. Isso era de proposito: toque sem querer ficava inofensivo e
    # a auditoria continuava registrando QUEM autorizou.
    #
    # `reinicia` quebra essa propriedade -- e destrutivo e derruba a venda
    # aberta. Por isso vem com tres travas, e nenhuma e decoracao:
    #   1. a tela pede CONFIRMACAO, com o numero do caixa, e avisa quando ha
    #      venda em andamento;
    #   2. `intervalo_acao` recusa repetir a mesma acao no mesmo caixa -- toque
    #      duplo em tablet e regra, nao excecao, e dois reboots seguidos
    #      derrubam a maquina duas vezes;
    #   3. quem executa de fato e o `mf-agente` dentro do PDV. Se o comando nao
    #      estiver na lista branca de la, nada acontece. O painel nao tem poder
    #      proprio: ele pede.
    # A lista branca da API. `teste` nao aparece na tela: existe para conferir
    # que o canal ate a maquina esta vivo sem tocar no venditor -- ele so roda
    # um `echo` do outro lado. Sem isso, a unica forma de testar o caminho
    # seria derrubar um caixa de verdade.
    ACOES = ("destrava", "reinicia", "volume-ler", "volume-set",
             "congela", "descongela", "teste")
    PISO_VOLUME = 30
    TETO_VOLUME = 100

    def confere_pin(self, pin, origem, leitor=False):
        """(ok, rotulo_ou_motivo). Sem PIN configurado, tudo passa.

        `leitor` e o que a TELA afirma sobre a origem -- ver o comentario em
        `pins_digitaveis`.
        """
        if not self.pins:
            return True, ""
        t = agora()
        tentado = str(pin or "")
        with self.lock_acao:
            erros, ate = self.pin_erros.get(origem, (0, 0))
            if t < ate:
                return False, "muitas tentativas — espere %d s" % int(ate - t + 1)
            # compare_digest e nao ==: comparacao normal sai no primeiro
            # caractere diferente, e isso vaza o PIN pelo tempo de resposta.
            # Percorre TODOS mesmo depois de achar: sair no primeiro acerto
            # faria o tempo de resposta contar em que posicao da lista o PIN
            # esta, que e meio caminho para descobrir qual e.
            achado = None
            for valido, rotulo in self.pins.items():
                if hmac.compare_digest(tentado, valido) and achado is None:
                    achado = rotulo
            if achado is not None:
                if not leitor and tentado not in self.pins_digitaveis:
                    # NAO conta como erro no freio: quem passou o cracha certo
                    # so errou o meio, e travar por isso puniria o acerto.
                    return False, "esta matrícula só vale passando o crachá"
                self.pin_erros.pop(origem, None)
                return True, achado
            erros += 1
            ate = t + 60 if erros >= 5 else 0
            self.pin_erros[origem] = (erros, ate)
        sys.stderr.write("PIN errado de %s (%d seguidos)\n" % (origem, erros))
        return False, "PIN incorreto"

    def entrar(self, pin, origem, leitor=False):
        """Confere o PIN e devolve um token de sessao."""
        ok, quem = self.confere_pin(pin, origem, leitor)
        if not ok:
            return False, quem
        token = secrets.token_urlsafe(24)
        with self.lock_acao:
            # A sessao carrega QUEM entrou, para a acao poder dizer depois.
            self.sessoes[token] = {"t": agora(), "quem": quem or "sem PIN"}
        sys.stderr.write("ENTROU %s por %s (%s)\n"
                         % (origem, quem or "sem PIN",
                            "crachá" if leitor else "digitado"))
        return True, token

    def sessao_ok(self, token):
        """Quem e o dono do token, ou None. Renova o relogio dele.

        Devolve string (nunca vazia) quando vale, para o chamador poder usar
        `if not quem:` sem confundir com \"entrou sem PIN\".
        """
        if not self.pins:
            return "sem PIN"     # sem PIN configurado, painel aberto
        if not token:
            return None
        t = agora()
        with self.lock_acao:
            # Limpa o que ja morreu, para o dicionario nao crescer para sempre.
            for k in [k for k, v in self.sessoes.items()
                      if t - v["t"] > self.sessao_validade]:
                self.sessoes.pop(k, None)
            s = self.sessoes.get(token)
            if s is None:
                return None
            s["t"] = t
            return s["quem"]

    def comando(self, pdv, acao, valor=None, quem="?"):
        if acao not in self.ACOES:
            return False, "ação desconhecida"
        try:
            c = self.caixas.get(int(pdv))
        except (TypeError, ValueError):
            c = None
        if c is None:
            return False, "PDV desconhecido"

        # 🔴 NAO CONGELA NO PAGAMENTO COM CARTAO. Pausado ali, a conversa com a
        # SiTef expira do lado do banco, e o pior caso e cartao cobrado sem o
        # pagamento registrado na venda.
        if acao == "congela":
            with c.lock:
                estado_agora = c.estado
            if estado_agora == "EFTPAY":
                return False, ("o %s está no pagamento com cartão — congelar "
                               "agora pode cobrar sem registrar" % c.pdv)

        t = agora()
        with self.lock_acao:
            ultima = self.ultima_acao.get((c.pdv, acao))
            # Volume e leitura nao entram na trava: a barra e para ser
            # arrastada, e travar isso seria travar o proprio uso.
            # Descongelar tambem nao: soltar um caixa nunca pode esperar.
            if (not acao.startswith("volume")
                    and acao not in ("teste", "descongela")
                    and ultima is not None
                    and t - ultima < self.intervalo_acao):
                return False, ("aguarde %d s para repetir"
                               % (int(self.intervalo_acao - (t - ultima)) + 1))
            self.ultima_acao[(c.pdv, acao)] = t

        # 🔴 O COMANDO NAO VEM DAQUI. Este metodo passa o NOME da acao para o
        # `acao-pdv.exp`, e e la dentro que "destrava" vira `pkill vend` e
        # "reinicia" vira `reboot`. Nao existe caminho que leve texto vindo da
        # rede para a linha de comando do PDV -- o script recusa nome fora da
        # lista, e isso foi testado com `reboot; rm -rf /` como parametro.
        #
        # Por que nao a chave `monitorfiscal`: ela esta presa a `command=` e so
        # aceita a lista do mf-agente (log-seguir, venditor-seguir, plu-mapa,
        # volume-*). Comando arbitrario por ela responde "comando nao
        # permitido". O PDV aceita root por senha, entao o expect usa esse
        # caminho e nada precisa mudar nas maquinas.
        roteiro = self.cfg.get("acao_roteiro",
                               os.path.join(AQUI, "..", "acao-pdv.exp"))
        # O volume e o UNICO dado que atravessa para a maquina. Ele e travado
        # aqui e travado de novo no roteiro -- as duas pontas, porque uma so
        # nao e trava, e sim confianca.
        extra = []
        if acao == "volume-set":
            try:
                v = int(valor)
            except (TypeError, ValueError):
                return False, "volume inválido"
            v = max(self.PISO_VOLUME, min(self.TETO_VOLUME, v))
            extra = [str(v)]

        try:
            r = subprocess.run(["/usr/bin/expect", roteiro, c.host, acao] + extra,
                               capture_output=True, timeout=40)
            bruto = (r.stdout.decode("utf-8", "replace").strip()
                     or r.stderr.decode("utf-8", "replace").strip())
            saida = bruto
            # A ultima linha util; o expect ecoa o comando enviado antes dela.
            saida = [l for l in saida.splitlines() if l.strip()]
            saida = saida[-1].strip() if saida else "sem resposta"
            ok = r.returncode == 0
        except subprocess.TimeoutExpired:
            ok, saida, bruto = False, "tempo esgotado", ""
        except Exception as e:                             # noqa: BLE001
            ok, saida, bruto = False, "%s: %s" % (type(e).__name__, e), ""

        # O reboot derruba a sessao SSH no meio: o comando "falha" mesmo tendo
        # funcionado. Tratar isso como erro faria a tela dizer que nao
        # reiniciou justamente quando reiniciou.
        if acao.startswith("volume"):
            # O `amixer` do outro lado devolve o volume REAL depois de subir --
            # o mesmo principio do volume-definir: comando aceito nao e comando
            # aplicado, entao a tela mostra o que a maquina respondeu.
            #
            # `findall` e nao `search`: o eco do proprio comando traz "10%+",
            # entao o primeiro casamento seria o passo, nao o resultado. O
            # ultimo e o que a maquina leu de volta.
            achados = re.findall(r"(\d{1,3})%", bruto)
            if achados:
                ok, saida = True, achados[-1]
            else:
                ok, saida = False, "não consegui ler o volume de volta"
        elif acao == "reinicia" and ("caiu" in saida.lower() or ok):
            saida = "reiniciando — a máquina volta em ~1 min"
            ok = True
        elif acao == "destrava" and ok:
            saida = "destravado — o venditor reinicia sozinho"
        elif acao in ("congela", "descongela"):
            ok, saida = self.resultado_congela(acao, bruto, ok)

        if ok and acao in ("congela", "descongela", "destrava", "reinicia"):
            with c.lock:
                if acao == "congela":
                    c.congelado_em = agora()
                    c.congelado_por = quem
                else:
                    c.congelado_em = None
                    c.congelado_por = None

        # Acao na maquina fica no log do coletor. Sem isso ninguem consegue
        # responder depois "quem reiniciou o 224 as 11h".
        # 🔴 QUEM aparece aqui, e essa era a lacuna. O botao "Liberar" original
        # nao executava nada justamente para a auditoria do venditor registrar
        # quem autorizou; as acoes desta tela executam com a credencial do
        # servidor, entao sem isto ninguem responderia depois "quem reiniciou o
        # 224 as 11h". Com PIN por pessoa, o log responde.
        sys.stderr.write("ACAO %s pdv=%s por %s -> %s %s\n"
                         % (acao, c.pdv, quem, "ok" if ok else "FALHOU",
                            saida[:120]))
        return ok, saida


    @staticmethod
    def resultado_congela(acao, bruto, ok_ssh):
        """Le o estado REAL que o `ps` devolveu. Comando aceito nao e caixa
        congelado -- a tela so diz "congelado" se a maquina disse T.

        Casa LINHA INTEIRA: o terminal ecoa o comando enviado, e o eco tambem
        contem "MF-ESTADO-" e "MF-SEM-VENDITOR".
        """
        if CONGELA_SEM.search(bruto or ""):
            return False, "o venditor não está rodando nesse caixa"
        achados = CONGELA_ESTADO.findall(bruto or "")
        if not achados:
            return False, ("sem resposta da máquina" if ok_ssh
                           else "não consegui entrar no caixa")
        est = achados[-1]
        if acao == "congela":
            if est == "T":
                return True, ("congelado — solta sozinho em %d min"
                              % (CONGELA_MAX // 60))
            return False, "não congelou (estado %s)" % est
        if est != "T":
            return True, ("descongelado — confira a cesta: o que foi passado "
                          "ou tocado enquanto estava congelado entra agora")
        return False, "continua congelado"


class Handler(BaseHTTPRequestHandler):
    servico = None
    raiz_web = None

    def _json(self, codigo, corpo):
        dados = json.dumps(corpo, ensure_ascii=False).encode("utf-8")
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(dados)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(dados)

    def _sessao(self):
        """Dono do token do cabecalho, ou None. Vale para tudo que devolve ou
        muda dado."""
        return self.servico.sessao_ok(self.headers.get("X-MF-Token"))

    def do_GET(self):
        caminho, _, consulta = self.path.partition("?")
        args = dict(
            p.split("=", 1) for p in consulta.split("&") if "=" in p
        )
        # Saude do processo, SEM sessao. Existe para o healthcheck do Docker:
        # o antigo batia em /api/estado, que hoje responde 401 -- o container
        # ficaria "unhealthy" para sempre e o compose o reiniciaria em circulo.
        #
        # So CONTAGEM, nunca o estado de um caixa nem cesta: um endpoint aberto
        # nao pode virar a porta dos fundos que a tranca fechou na frente.
        if caminho == "/api/saude":
            cx = list(self.servico.caixas.values())
            return self._json(200, {
                "ok": True,
                "caixas": len(cx),
                "conectados": sum(1 for c in cx if c.conectado),
                # So contagem e horario -- nada de produto nem de cesta, porque
                # esta rota nao pede sessao.
                "catalogo": len(self.servico.catalogo.mapa),
                "alcool": len(self.servico.catalogo.alcool),
                "catalogo_em": _hora_txt(self.servico.catalogo.carregado_em),
                "catalogo_proxima": _hora_txt(
                    getattr(self.servico.recarga, "proxima", None)),
            })

        # 🔴 A TRANCA E AQUI, NAO NA TELA. Overlay de PIN no navegador nao
        # protege nada: bastaria pedir /api/estado direto para ver o estado dos
        # caixas E a cesta do cliente que esta no caixa agora. Quem barra e o
        # servidor, e o que ele barra e o DADO.
        if caminho.startswith("/api/") and not self._sessao():
            return self._json(401, {"ok": False, "erro": "sessão exigida"})
        if caminho == "/api/estado":
            return self._json(200, self.servico.estado())
        if caminho == "/api/volume":
            ok, saida = self.servico.volume_ler(int(args.get("pdv", 0) or 0))
            return self._json(200 if ok else 502, {"ok": ok, "volume": saida})
        if caminho in ("/", "/index.html"):
            return self._arquivo("index.html")
        if caminho.startswith("/") and ".." not in caminho:
            return self._arquivo(caminho.lstrip("/"))
        return self._json(404, {"ok": False, "erro": "não encontrado"})

    def do_POST(self):
        caminho, _, _ = self.path.partition("?")
        if caminho not in ("/api/volume", "/api/comando", "/api/entrar"):
            return self._json(404, {"ok": False, "erro": "não encontrado"})
        try:
            n = int(self.headers.get("Content-Length") or 0)
            corpo = json.loads(self.rfile.read(n).decode("utf-8") or "{}")
        except Exception:                                  # noqa: BLE001
            return self._json(400, {"ok": False, "erro": "corpo inválido"})

        # Unico caminho aberto: e por ele que se consegue a sessao.
        if caminho == "/api/entrar":
            ok, r = self.servico.entrar(corpo.get("pin"),
                                        self.client_address[0],
                                        bool(corpo.get("leitor")))
            return self._json(200 if ok else 403,
                              {"ok": ok, "token": r} if ok
                              else {"ok": False, "erro": r})

        if not self._sessao():
            return self._json(401, {"ok": False, "erro": "sessão exigida"})
        if caminho == "/api/comando":
            ok, saida = self.servico.comando(corpo.get("pdv"),
                                             corpo.get("acao"),
                                             corpo.get("valor"),
                                             self._sessao() or "?")
            return self._json(200 if ok else 502,
                              {"ok": ok, "resposta": saida})
        ok, saida = self.servico.volume_definir(corpo.get("pdv"), corpo.get("volume"))
        return self._json(200 if ok else 502, {"ok": ok, "volume": saida})

    def _arquivo(self, rel):
        if not self.raiz_web:
            return self._json(404, {"ok": False, "erro": "sem front-end"})
        caminho = os.path.normpath(os.path.join(self.raiz_web, rel))
        if not caminho.startswith(os.path.abspath(self.raiz_web)):
            return self._json(403, {"ok": False, "erro": "proibido"})
        if not os.path.isfile(caminho):
            return self._json(404, {"ok": False, "erro": "não encontrado"})
        tipo = {
            ".html": "text/html; charset=utf-8",
            ".js": "application/javascript; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".png": "image/png",
            ".mp3": "audio/mpeg",
            ".ogg": "audio/ogg",
        }.get(os.path.splitext(caminho)[1], "application/octet-stream")
        with open(caminho, "rb") as fh:
            dados = fh.read()
        self.send_response(200)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(dados)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(dados)

    def log_message(self, fmt, *a):
        # O log de acesso nao acrescenta nada e polui o journal do container.
        pass


def main():
    if not os.path.isfile(CONFIG):
        sys.stderr.write("config nao encontrada: %s\n" % CONFIG)
        sys.stderr.write("copie config.example.json para config.json\n")
        return 2
    with open(CONFIG, encoding="utf-8") as fh:
        cfg = json.load(fh)

    servico = Servico(cfg)
    servico.inicia()

    Handler.servico = servico
    Handler.raiz_web = os.path.abspath(
        os.path.join(AQUI, "..", cfg.get("web", "web"))
    )
    porta = int(cfg.get("porta", 8080))
    sys.stderr.write(
        "Monitor Fiscal na porta %d · %d máquinas · alerta acima de %s s\n"
        % (porta, len(servico.caixas), servico.limiar_alerta)
    )
    ThreadingHTTPServer(("0.0.0.0", porta), Handler).serve_forever()


if __name__ == "__main__":
    sys.exit(main() or 0)
