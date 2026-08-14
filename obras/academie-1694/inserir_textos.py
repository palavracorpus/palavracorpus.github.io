#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
inserir_textos.py

Recebe o texto corrido de uma peca liminar (colado num .txt) e o distribui
pelas vistas do fac-simile, cortando nos pontos onde cada pagina comeca.

Os pontos de corte foram lidos diretamente nas imagens do fac-simile. Tres
paginas da Preface comecam no meio de uma palavra (Pro-|nonciation,
Li-|vres, af-|fection); por isso os marcadores sao fragmentos, e nao
palavras inteiras.

Uso:
    python inserir_textos.py --secao preface --arquivo preface_fr.txt
    python inserir_textos.py --secao preface --arquivo preface_fr.txt --simular

Com --simular nada e gravado: o script so mostra onde cortaria.
"""

import argparse
import json
import re
import shutil
import sys
import unicodedata
from pathlib import Path

# --------------------------------------------------------------- marcadores
# vista -> fragmento com que a pagina comeca, tal como se le na imagem
CORTES = {
    "preface": [
        (9,  "que l'Academie Françoise eut esté establie"),
        (10, "On dira peut-estre qu'on ne peut jamais s'asseurer"),
        (11, "les Synonymes, c'est à dire les mots"),
        (12, "selon le genre & le nombre du Substantif"),
        (13, "Mais il y en a qui se sont avilis"),
        (14, "nonciation d'une Langue qui luy est estrangere"),
        (15, "vres d'observations sur la Langue Latine"),
        (16, "fection particuliere pour cette Compagnie"),
        (17, "Monsieur Colbert qui estoit de l'Academie"),
    ],
    # A Epistre nao esta no site da Academie (so as nove prefaces).
    # Os marcadores ficam prontos para quando o texto for obtido.
    "epistre": [
        (5,  "AU ROY"),
        (6,  "dont l'Eloquence & la Poesie peuvent former des éloges"),
        (7,  "C'est sur de tels fondemens"),
        (8,  "VOSTRE MAJESTE"),
    ],
}

FONTE = {
    "preface": {
        "credito": "Académie française, « Préface de la première édition (1694) », in Les neuf préfaces du Dictionnaire.",
        "url": "https://www.academie-francaise.fr/le-dictionnaire-les-neuf-prefaces/preface-de-la-premiere-edition-1694",
        "natureza": "transcricao_literal",
    },
    "epistre": {"credito": "", "url": "", "natureza": "transcricao_literal"},
}


def _expandir(ch: str) -> str:
    """Forma de comparação de um caractere: pode devolver '', 1 ou 2 caracteres."""
    ch = {"\u2019": "'", "\u2018": "'", "\u201c": '"', "\u201d": '"',
          "\u0153": "oe", "\u0152": "oe", "\u017f": "s"}.get(ch, ch)
    ch = unicodedata.normalize("NFD", ch)
    ch = "".join(c for c in ch if unicodedata.category(c) != "Mn")
    return ch.lower()


def normalizar_mapeado(s: str):
    """Devolve (texto_normalizado, mapa) com mapa[i] = índice no texto original."""
    saida, mapa = [], []
    for i, ch in enumerate(s):
        if ch.isspace():
            if saida and saida[-1] == " ":
                continue
            saida.append(" ")
            mapa.append(i)
            continue
        for c in _expandir(ch):
            saida.append(c)
            mapa.append(i)
    return "".join(saida), mapa


def normalizar(s: str) -> str:
    return normalizar_mapeado(s)[0].strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--secao", required=True, choices=sorted(CORTES))
    ap.add_argument("--arquivo", required=True)
    ap.add_argument("--textos", default="textos.json")
    ap.add_argument("--simular", action="store_true")
    args = ap.parse_args()

    bruto = Path(args.arquivo).read_text(encoding="utf-8")
    bruto = bruto.replace("\r\n", "\n").strip()
    if not bruto:
        sys.exit("ERRO: o arquivo está vazio.")

    plano, mapa = normalizar_mapeado(bruto)

    cortes = CORTES[args.secao]

    # ------------------------------------------------ localizar cada corte
    posicoes, anterior = [], -1
    for vista, marcador in cortes:
        alvo = normalizar(marcador)
        p = plano.find(alvo, anterior + 1)
        if p == -1:
            sys.exit(
                "ERRO: não encontrei o início da vista %d.\n"
                "  Procurei por: %s\n"
                "  Verifique se o texto colado está completo e é o da seção certa."
                % (vista, marcador)
            )
        if p <= anterior:
            sys.exit("ERRO: a vista %d apareceu fora de ordem no texto." % vista)
        posicoes.append((vista, p))
        anterior = p

    # a primeira vista pode nao comecar no caractere 0: a Academie omite a
    # letra da capitular historiada (o A de APRE'S), entao sobra um resto antes
    resto_inicial = posicoes[0][1]
    if resto_inicial > 0:
        print("AVISO: %d caractere(s) antes do primeiro corte serão anexados à "
              "vista %d.\n  Trecho: %r"
              % (resto_inicial, posicoes[0][0], bruto[:min(resto_inicial, 60)]))
        posicoes[0] = (posicoes[0][0], 0)

    # ------------------------------------------------------------ recortar
    fatias = []
    for idx, (vista, p) in enumerate(posicoes):
        ini = mapa[p] if p < len(mapa) else len(bruto)
        if idx + 1 < len(posicoes):
            pf = posicoes[idx + 1][1]
            fim = mapa[pf] if pf < len(mapa) else len(bruto)
        else:
            fim = len(bruto)
        fatias.append((vista, bruto[ini:fim].strip()))

    # ------------------------------------------------------------ validar
    soma = sum(len(t) for _, t in fatias)
    vazias = [v for v, t in fatias if not t]
    print("\nseção: %s   vistas: %d   caracteres no arquivo: %d   nas fatias: %d"
          % (args.secao, len(fatias), len(bruto), soma))
    for v, t in fatias:
        primeiro = " ".join(t.split()[:7])
        print("  vista %2d  %6d car.  %s…" % (v, len(t), primeiro))
    if vazias:
        sys.exit("ERRO: as vistas %s ficaram sem texto." % vazias)
    if soma < len(bruto) * 0.95:
        sys.exit("ERRO: perda de texto no recorte (%d de %d)." % (soma, len(bruto)))

    if args.simular:
        print("\n--simular: nada foi gravado.")
        return

    # ------------------------------------------------------------- gravar
    caminho = Path(args.textos)
    shutil.copy(caminho, caminho.with_suffix(".json.bak"))
    dados = json.loads(caminho.read_text(encoding="utf-8"))

    por_vista = {v["vista"]: v for v in dados["vistas"]}
    for vista, texto in fatias:
        if vista not in por_vista:
            sys.exit("ERRO: vista %d não existe em %s." % (vista, caminho))
        reg = por_vista[vista]
        reg["fr"]["texto"] = texto
        reg["estado"] = "transcrito"
        reg["fonte_texto"] = FONTE[args.secao]
        for lg in ("pt", "es", "en"):
            if not reg[lg].get("texto"):
                reg[lg]["texto"] = None
                reg[lg]["traducao_pendente"] = True

    caminho.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\ngravado em %s  (cópia de segurança em %s)"
          % (caminho, caminho.with_suffix(".json.bak")))
    print("As traduções pt/es/en dessas vistas ficaram marcadas como pendentes.")


if __name__ == "__main__":
    main()
