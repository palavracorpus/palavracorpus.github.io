#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
acad1694_processar.py

Prepara as vistas do fac-simile dos pretextos do Dictionnaire de l'Academie
francoise (1a ed., 1694, Tomo I) para publicacao web.

PRINCIPIO: intervencao minima. O objetivo e recortar o fundo do scanner e
uniformizar o ponto de branco entre as vistas para que a galeria nao "pisque".
NAO ha binarizacao, NAO ha despeckle, NAO ha remocao de foxing, manchas,
transparencia do verso nem das anotacoes a lapis. Esses elementos sao parte
do objeto e sao evidencia.

Entrada : diretorio com 1.jpeg .. N.jpeg (numeracao de vista)
Saida   : paginas/ (exibicao), thumbs/ (miniaturas), relatorio.json

Uso:
    python acad1694_processar.py --entrada raw --saida saida
"""

import argparse
import json
import os
from pathlib import Path

import numpy as np
from PIL import Image, ImageEnhance

Image.MAX_IMAGE_PIXELS = None

# ---------------------------------------------------------------- parametros

WARMTH_MIN = 12      # (R+G)/2 - B minimo para considerar "papel"
LUM_MIN = 60         # luminancia minima para considerar "papel"
COL_FRAC = 0.50      # fracao de pixels-papel numa coluna/linha para aceita-la
TRIM = 3             # erosao final, em px, para eliminar a franja do recorte
ALVO_PAPEL = 236     # ponto de branco alvo do papel (0-255)
GANHO_MAX = 1.35     # teto do ganho, para nao estourar vistas ja claras
CONTRASTE = 1.06     # leve realce de contraste
LARG_THUMB = 220


def mascara_papel(a: np.ndarray) -> np.ndarray:
    """Papel = quente (amarelado) e nao muito escuro. Fundo do scanner = neutro."""
    r, g, b = a[:, :, 0], a[:, :, 1], a[:, :, 2]
    calor = (r.astype(np.int16) + g) / 2 - b
    lum = a.mean(axis=2)
    return (calor > WARMTH_MIN) & (lum > LUM_MIN)


def caixa_do_papel(a: np.ndarray):
    m = mascara_papel(a)
    cols = np.where(m.mean(axis=0) > COL_FRAC)[0]
    rows = np.where(m.mean(axis=1) > COL_FRAC)[0]
    if len(cols) == 0 or len(rows) == 0:
        return None
    x0, x1 = int(cols.min()), int(cols.max())
    y0, y1 = int(rows.min()), int(rows.max())
    h, w = a.shape[:2]
    x0 = min(x0 + TRIM, w - 1)
    y0 = min(y0 + TRIM, h - 1)
    x1 = max(x1 - TRIM, x0 + 1)
    y1 = max(y1 - TRIM, y0 + 1)
    return x0, y0, x1, y1


def normalizar_tom(im: Image.Image) -> tuple:
    """Ganho suave para levar o papel ao mesmo ponto de branco em todas as vistas."""
    a = np.asarray(im).astype(np.float32)
    lum = a.mean(axis=2)
    # o papel e a moda clara da imagem: usa o percentil 92 como referencia
    ref = float(np.percentile(lum, 92))
    ganho = 1.0 if ref <= 0 else min(ALVO_PAPEL / ref, GANHO_MAX)
    a = np.clip(a * ganho, 0, 255).astype(np.uint8)
    out = ImageEnhance.Contrast(Image.fromarray(a)).enhance(CONTRASTE)
    return out, ref, ganho


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--entrada", required=True)
    ap.add_argument("--saida", required=True)
    ap.add_argument("--altura", type=int, default=1350,
                    help="altura da imagem de exibicao, em px")
    args = ap.parse_args()

    ent = Path(args.entrada)
    sai = Path(args.saida)
    (sai / "paginas").mkdir(parents=True, exist_ok=True)
    (sai / "thumbs").mkdir(parents=True, exist_ok=True)

    fontes = sorted(ent.glob("*.jpeg"), key=lambda p: int(p.stem))
    n_entrada = len(fontes)
    if n_entrada == 0:
        raise SystemExit("Nenhum .jpeg encontrado em %s" % ent)

    registros = []
    for p in fontes:
        vista = int(p.stem)
        im = Image.open(p).convert("RGB")
        orig_w, orig_h = im.size

        a = np.asarray(im)
        caixa = caixa_do_papel(a)
        if caixa is None:
            recorte = im
            caixa_reg = None
        else:
            x0, y0, x1, y1 = caixa
            recorte = im.crop((x0, y0, x1 + 1, y1 + 1))
            caixa_reg = [x0, y0, x1, y1]

        rec_w, rec_h = recorte.size
        tratada, ref, ganho = normalizar_tom(recorte)

        # exibicao: altura uniforme, largura proporcional
        escala = args.altura / rec_h
        disp = tratada.resize(
            (max(1, round(rec_w * escala)), args.altura), Image.LANCZOS
        )
        base = "%02d" % vista
        disp.save(sai / "paginas" / (base + ".webp"), "WEBP", quality=86, method=6)
        disp.save(sai / "paginas" / (base + ".jpg"), "JPEG", quality=88,
                  optimize=True, progressive=True)

        th = tratada.copy()
        th.thumbnail((LARG_THUMB, LARG_THUMB * 3), Image.LANCZOS)
        th.save(sai / "thumbs" / (base + ".webp"), "WEBP", quality=80, method=6)

        registros.append({
            "vista": vista,
            "arquivo_fonte": p.name,
            "px_original": [orig_w, orig_h],
            "caixa_papel": caixa_reg,
            "px_recortado": [rec_w, rec_h],
            "px_exibicao": list(disp.size),
            "pct_area_removida": round(
                100 * (1 - (rec_w * rec_h) / (orig_w * orig_h)), 2),
            "papel_p92_antes": round(ref, 1),
            "ganho_aplicado": round(ganho, 4),
        })

    # ------------------------------------------------------------ validacao
    n_paginas = len(list((sai / "paginas").glob("*.webp")))
    n_thumbs = len(list((sai / "thumbs").glob("*.webp")))
    vistas = [r["vista"] for r in registros]
    lacunas = [v for v in range(min(vistas), max(vistas) + 1) if v not in vistas]

    relatorio = {
        "obra": "Dictionnaire de l'Academie francoise, 1a ed., 1694, Tomo I",
        "recorte": "pretextos + primeira pagina do dicionario",
        "parametros": {
            "warmth_min": WARMTH_MIN, "lum_min": LUM_MIN, "col_frac": COL_FRAC,
            "trim_px": TRIM, "alvo_papel": ALVO_PAPEL, "ganho_max": GANHO_MAX,
            "contraste": CONTRASTE, "altura_exibicao": args.altura,
        },
        "tratamento_nao_aplicado": [
            "binarizacao", "despeckle / denoise", "remocao de foxing e manchas",
            "remocao da transparencia do verso", "remocao de anotacoes a lapis",
            "deskew", "preenchimento de bordas",
        ],
        "validacao": {
            "vistas_entrada": n_entrada,
            "vistas_processadas": len(registros),
            "webp_paginas": n_paginas,
            "webp_thumbs": n_thumbs,
            "lacunas_na_numeracao": lacunas,
            "integro": (n_entrada == len(registros) == n_paginas == n_thumbs
                        and not lacunas),
        },
        "vistas": registros,
    }
    with open(sai / "relatorio.json", "w", encoding="utf-8") as f:
        json.dump(relatorio, f, ensure_ascii=False, indent=2)

    v = relatorio["validacao"]
    print("entrada=%d  processadas=%d  webp=%d  thumbs=%d  lacunas=%s  INTEGRO=%s"
          % (v["vistas_entrada"], v["vistas_processadas"], v["webp_paginas"],
             v["webp_thumbs"], v["lacunas_na_numeracao"], v["integro"]))


if __name__ == "__main__":
    main()
