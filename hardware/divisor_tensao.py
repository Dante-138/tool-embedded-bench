"""Divisor resistivo para leitura de tensão (ex.: monitor de bateria no ADC).

Convenção: R1 fica entre a tensão medida e o nó do ADC; R2 fica entre o nó e o GND.
    Vout = Vin * R2 / (R1 + R2)

Uso:
    python hardware/divisor_tensao.py saida   --vin 4.2 --r1 100k --r2 100k --tol 1
    python hardware/divisor_tensao.py projetar --vin-max 4.2 --vout 2.1 \\
        --rtotal-min 200k --rtotal-max 2M --serie e24
    python hardware/divisor_tensao.py adc --contagens 2500 --r1 100k --r2 100k --vref 3.3 --bits 12

Resistores aceitam: 470, 4.7k, 4k7, 2R2, 1M (M maiúsculo = mega).

Limites: o ADC é tratado como linear de 0 a Vref. ADCs reais (o do ESP32, por
exemplo) têm não linearidade e dependem da atenuação e da calibração, e isso
não é modelado aqui. Resistência total alta reduz o consumo do divisor, mas
aumenta o erro por corrente de entrada do ADC e por ruído.
"""

import argparse
import itertools
import math
import re
import sys

SERIES = {
    "e12": [1.0, 1.2, 1.5, 1.8, 2.2, 2.7, 3.3, 3.9, 4.7, 5.6, 6.8, 8.2],
    "e24": [
        1.0,
        1.1,
        1.2,
        1.3,
        1.5,
        1.6,
        1.8,
        2.0,
        2.2,
        2.4,
        2.7,
        3.0,
        3.3,
        3.6,
        3.9,
        4.3,
        4.7,
        5.1,
        5.6,
        6.2,
        6.8,
        7.5,
        8.2,
        9.1,
    ],
}

_RE_NOTACAO = re.compile(r"^(\d+)([kKMR])(\d+)$")  # 4k7, 2R2, 1M5
_RE_SUFIXO = re.compile(r"^(\d+(?:\.\d+)?)([kKM]?)$")  # 100k, 4.7k, 1M, 470
_MULT = {"": 1.0, "k": 1e3, "K": 1e3, "M": 1e6, "R": 1.0}


def parse_resistencia(texto):
    t = texto.strip()
    m = _RE_NOTACAO.match(t)
    if m:
        inteiro, letra, fracao = m.groups()
        return round(float(f"{inteiro}.{fracao}") * _MULT[letra], 6)
    m = _RE_SUFIXO.match(t)
    if m:
        numero, sufixo = m.groups()
        return round(float(numero) * _MULT[sufixo], 6)
    raise ValueError(f"resistência inválida: {texto!r} (use 470, 4.7k, 4k7, 2R2 ou 1M)")


def formatar_resistencia(valor):
    if valor >= 1e6:
        return f"{valor / 1e6:g}M"
    if valor >= 1e3:
        return f"{valor / 1e3:g}k"
    return f"{valor:g}"


def tensao_saida(vin, r1, r2):
    return vin * r2 / (r1 + r2)


def vin_a_partir_da_saida(vout, r1, r2):
    return vout * (r1 + r2) / r2


def corrente_divisor_ua(vin, r1, r2):
    """Corrente que o divisor puxa da fonte medida, em microampères."""
    return vin / (r1 + r2) * 1e6


def contagens_adc(vout, vref, bits):
    maximo = 2**bits - 1
    return min(maximo, max(0, round(vout / vref * maximo)))


def vin_de_contagens(contagens, r1, r2, vref, bits):
    vout = contagens / (2**bits - 1) * vref
    return vin_a_partir_da_saida(vout, r1, r2)


def tolerancia_pior_caso(vin, r1, r2, tol_pct):
    """(Vout_min, Vout_max) com os dois resistores no extremo da tolerância."""
    t = tol_pct / 100.0
    vmin = vin * r2 * (1 - t) / (r1 * (1 + t) + r2 * (1 - t))
    vmax = vin * r2 * (1 + t) / (r1 * (1 - t) + r2 * (1 + t))
    return vmin, vmax


def valores_da_serie(serie, decada_min=1, decada_max=6):
    """Valores comerciais de 10 ohm até ~9,1 Mohm (décadas 10^1 a 10^6)."""
    base = SERIES[serie]
    return sorted({round(b * 10**d, 3) for b in base for d in range(decada_min, decada_max + 1)})


def projetar(vin_max, vout_alvo, serie="e24", rtotal_min=0.0, rtotal_max=math.inf, quantos=5):
    """Melhores pares (r1, r2) da série. Ordena por menor erro; empate vai para a
    maior resistência total (menor consumo do divisor).
    Retorna lista de dicts com r1, r2, vout, erro_pct e corrente_ua."""
    valores = valores_da_serie(serie)
    candidatos = []
    for r1, r2 in itertools.product(valores, repeat=2):
        total = r1 + r2
        if not rtotal_min <= total <= rtotal_max:
            continue
        vout = tensao_saida(vin_max, r1, r2)
        erro = abs(vout - vout_alvo) / vout_alvo * 100
        candidatos.append((round(erro, 9), -total, r1, r2, vout))
    candidatos.sort()
    return [
        {"r1": r1, "r2": r2, "vout": vout, "erro_pct": erro, "corrente_ua": corrente_divisor_ua(vin_max, r1, r2)}
        for erro, _, r1, r2, vout in candidatos[:quantos]
    ]


def _resistencia_arg(texto):
    try:
        return parse_resistencia(texto)
    except ValueError as erro:
        raise argparse.ArgumentTypeError(str(erro))


def main(argv=None):
    ap = argparse.ArgumentParser(description="Divisor resistivo: saída, projeto e leitura de ADC.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("saida", help="tensão de saída de um divisor conhecido")
    s.add_argument("--vin", type=float, required=True)
    s.add_argument("--r1", type=_resistencia_arg, required=True)
    s.add_argument("--r2", type=_resistencia_arg, required=True)
    s.add_argument("--tol", type=float, help="tolerância dos resistores em %% (mostra pior caso)")

    p = sub.add_parser("projetar", help="escolhe R1/R2 comerciais para uma tensão alvo")
    p.add_argument("--vin-max", type=float, required=True, help="maior tensão a medir")
    p.add_argument("--vout", type=float, required=True, help="tensão desejada no ADC nesse ponto")
    p.add_argument("--serie", choices=sorted(SERIES), default="e24")
    p.add_argument("--rtotal-min", type=_resistencia_arg, default=0.0)
    p.add_argument("--rtotal-max", type=_resistencia_arg, default=math.inf)
    p.add_argument("--quantos", type=int, default=5)

    a = sub.add_parser("adc", help="tensão medida a partir das contagens do ADC")
    a.add_argument("--contagens", type=int, required=True)
    a.add_argument("--r1", type=_resistencia_arg, required=True)
    a.add_argument("--r2", type=_resistencia_arg, required=True)
    a.add_argument("--vref", type=float, required=True)
    a.add_argument("--bits", type=int, default=12)

    args = ap.parse_args(argv)

    if args.cmd == "saida":
        vout = tensao_saida(args.vin, args.r1, args.r2)
        print(f"Vout = {vout:.4f} V (razão {args.r2 / (args.r1 + args.r2):.4f})")
        print(f"Corrente do divisor: {corrente_divisor_ua(args.vin, args.r1, args.r2):.2f} uA")
        if args.tol is not None:
            vmin, vmax = tolerancia_pior_caso(args.vin, args.r1, args.r2, args.tol)
            print(f"Pior caso com +/-{args.tol:g}%: {vmin:.4f} V a {vmax:.4f} V")
    elif args.cmd == "projetar":
        resultado = projetar(args.vin_max, args.vout, args.serie, args.rtotal_min, args.rtotal_max, args.quantos)
        if not resultado:
            print("nenhum par dentro dos limites de resistência total", file=sys.stderr)
            return 1
        print(f"{'R1':>8} {'R2':>8} {'Vout (V)':>9} {'erro %':>8} {'corrente uA':>12}")
        for r in resultado:
            print(
                f"{formatar_resistencia(r['r1']):>8} {formatar_resistencia(r['r2']):>8} "
                f"{r['vout']:>9.4f} {r['erro_pct']:>8.3f} {r['corrente_ua']:>12.2f}"
            )
    else:
        vin = vin_de_contagens(args.contagens, args.r1, args.r2, args.vref, args.bits)
        print(f"Tensão medida: {vin:.4f} V ({args.contagens} contagens de {2**args.bits - 1})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
