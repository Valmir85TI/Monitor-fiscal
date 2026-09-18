#!/bin/sh
# Troca um arquivo do painel pelo .novo, de forma ATOMICA e com validacao.
#
# Por que existe: o pscp escreve POR CIMA, no lugar. Uma pagina carregada
# durante o upload pega o arquivo pela metade -- o JavaScript vem truncado, o
# script morre com erro de sintaxe, e o painel CONGELA no ultimo desenho. Pior:
# a animacao do CSS continua, entao a celula fica piscando o alerta para sempre
# sobre um problema ja resolvido, e nenhum codigo em pagina pode se recuperar
# disso, porque o JS ja morreu.
#
# Aconteceu em 09/09 com o tablet da loja. `mv` no mesmo sistema de arquivos e
# atomico: quem esta lendo pega o arquivo velho INTEIRO ou o novo INTEIRO,
# nunca um pedaco dos dois.
#
#   uso: sh publicar.sh web/index.html
ALVO="$1"
NOVO="$ALVO.novo"

[ -f "$NOVO" ] || { echo "FALTA $NOVO"; exit 1; }

# so troca se o arquivo estiver inteiro
case "$ALVO" in
  *.html)
    tail -c 20 "$NOVO" | grep -q '</html>' || { echo "RECUSADO: $NOVO nao termina em </html>"; rm -f "$NOVO"; exit 1; }
    a=$(grep -c '<script>' "$NOVO"); b=$(grep -c '</script>' "$NOVO")
    [ "$a" = "$b" ] || { echo "RECUSADO: script abre $a e fecha $b"; rm -f "$NOVO"; exit 1; }
    ;;
  *.py)
    /usr/local/bin/python3 -m py_compile "$NOVO" || { echo "RECUSADO: $NOVO nao compila"; rm -f "$NOVO"; exit 1; }
    ;;
esac

mv "$NOVO" "$ALVO"
echo "publicado: $ALVO ($(wc -c < "$ALVO") bytes)"
