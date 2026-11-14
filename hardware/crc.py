"""Calculadora de CRC genérica (modelo Rocksoft/Williams) com algoritmos comuns.

Uso:
    python hardware/crc.py --listar
    python hardware/crc.py --algoritmo crc16-modbus --hex "01 03 00 00 00 0A"
    python hardware/crc.py --algoritmo crc32 --texto "123456789"

Um CRC fica definido por seis parâmetros: largura, polinômio, valor inicial,
reflexão da entrada, reflexão da saída e XOR final. Dois CRCs "de 16 bits"
podem diferir só na reflexão ou no valor inicial e dar resultados diferentes
para os mesmos dados. É por isso que o nome exato do algoritmo importa.

A implementação é bit a bit (clara, não rápida). Em firmware, gere uma tabela
de 256 entradas a partir dos mesmos parâmetros.
"""

import argparse
import sys
from dataclasses import dataclass


@dataclass(frozen=True)
class ParametrosCRC:
    largura: int
    poly: int
    init: int
    refin: bool
    refout: bool
    xorout: int


def _refletir(valor, bits):
    resultado = 0
    for i in range(bits):
        if valor & (1 << i):
            resultado |= 1 << (bits - 1 - i)
    return resultado


def calcular(dados, p):
    """CRC de `dados` (bytes) segundo os parâmetros `p`. Largura mínima: 8 bits."""
    if p.largura < 8:
        raise ValueError("largura mínima suportada: 8 bits")
    topo = 1 << (p.largura - 1)
    mascara = (1 << p.largura) - 1
    crc = p.init & mascara
    for byte in dados:
        if p.refin:
            byte = _refletir(byte, 8)
        crc ^= byte << (p.largura - 8)
        for _ in range(8):
            crc = (crc << 1) ^ p.poly if crc & topo else crc << 1
            crc &= mascara
    if p.refout:
        crc = _refletir(crc, p.largura)
    return (crc ^ p.xorout) & mascara


# Parâmetros do catálogo de CRCs (Rocksoft). Valor de verificação: CRC de b"123456789".
ALGORITMOS = {
    "crc8":             ParametrosCRC(8,  0x07,       0x00,       False, False, 0x00),        # 0xF4
    "crc8-maxim":       ParametrosCRC(8,  0x31,       0x00,       True,  True,  0x00),        # 0xA1 (1-Wire)
    "crc16-ccitt-false": ParametrosCRC(16, 0x1021,    0xFFFF,     False, False, 0x0000),      # 0x29B1
    "crc16-xmodem":     ParametrosCRC(16, 0x1021,     0x0000,     False, False, 0x0000),      # 0x31C3
    "crc16-kermit":     ParametrosCRC(16, 0x1021,     0x0000,     True,  True,  0x0000),      # 0x2189
    "crc16-modbus":     ParametrosCRC(16, 0x8005,     0xFFFF,     True,  True,  0x0000),      # 0x4B37
    "crc16-arc":        ParametrosCRC(16, 0x8005,     0x0000,     True,  True,  0x0000),      # 0xBB3D
    "crc32":            ParametrosCRC(32, 0x04C11DB7, 0xFFFFFFFF, True,  True,  0xFFFFFFFF),  # 0xCBF43926
    "crc32c":           ParametrosCRC(32, 0x1EDC6F41, 0xFFFFFFFF, True,  True,  0xFFFFFFFF),  # 0xE3069283
    "crc32-mpeg2":      ParametrosCRC(32, 0x04C11DB7, 0xFFFFFFFF, False, False, 0x00000000),  # 0x0376E6E7
}


def crc(dados, algoritmo):
    return calcular(dados, ALGORITMOS[algoritmo])


def hex_para_bytes(texto):
    limpo = texto.replace("0x", "").replace(",", " ").replace(":", " ")
    return bytes.fromhex("".join(limpo.split()))


def main(argv=None):
    ap = argparse.ArgumentParser(description="Calculadora de CRC (8/16/32 bits).")
    ap.add_argument("--listar", action="store_true", help="lista os algoritmos e seus parâmetros")
    ap.add_argument("--algoritmo", choices=sorted(ALGORITMOS))
    entrada = ap.add_mutually_exclusive_group()
    entrada.add_argument("--hex", help='bytes em hexadecimal, ex.: "01 03 00 00 00 0A"')
    entrada.add_argument("--texto", help="texto ASCII/UTF-8")
    args = ap.parse_args(argv)

    if args.listar:
        for nome, p in sorted(ALGORITMOS.items()):
            print(f"{nome:<18} largura={p.largura:<2} poly=0x{p.poly:0{p.largura // 4}X} "
                  f"init=0x{p.init:0{p.largura // 4}X} refin={int(p.refin)} refout={int(p.refout)} "
                  f"xorout=0x{p.xorout:0{p.largura // 4}X}")
        return 0

    if not args.algoritmo or (args.hex is None and args.texto is None):
        ap.error("informe --algoritmo e (--hex ou --texto), ou use --listar")

    try:
        dados = hex_para_bytes(args.hex) if args.hex is not None else args.texto.encode("utf-8")
    except ValueError as erro:
        print(f"erro: hexadecimal inválido ({erro})", file=sys.stderr)
        return 2

    valor = crc(dados, args.algoritmo)
    p = ALGORITMOS[args.algoritmo]
    n = p.largura // 8
    print(f"{args.algoritmo} sobre {len(dados)} byte(s) = 0x{valor:0{n * 2}X}")
    print(f"  bytes, big-endian:    {valor.to_bytes(n, 'big').hex(' ').upper()}")
    print(f"  bytes, little-endian: {valor.to_bytes(n, 'little').hex(' ').upper()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
