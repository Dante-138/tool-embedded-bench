"""Logger de porta serial com timestamp e reconexão automática.

Uso:
    python bancada/serial_logger.py --porta COM11
    python bancada/serial_logger.py --porta COM11 --saida logs/teste.log --max-segundos 60

Por que existe: o `idf.py monitor` exige um terminal interativo (TTY) e não
roda em automação. Este script lê a porta em qualquer contexto, grava cada
linha com timestamp e continua funcionando se a placa reiniciar ou o USB cair.

Sobre reset: abrir uma porta serial mexe nas linhas DTR/RTS, e em muitas placas
ESP32 isso reinicia o chip. Por padrão a porta é aberta com DTR/RTS em nível
baixo, o que evita o reset na maioria dos drivers USB-serial. Não há garantia:
se a placa reiniciar ao abrir a porta, o driver é o motivo.
"""

import argparse
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import serial

# Sequências de cor do ESP-IDF (ex.: "\x1b[0;32m") poluem o arquivo de log.
ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def carimbo(agora=None):
    """Timestamp local com milissegundos: 2026-09-29 14:03:07.412"""
    agora = agora or datetime.now()
    return f"{agora:%Y-%m-%d %H:%M:%S}.{agora.microsecond // 1000:03d}"


def remover_ansi(texto):
    return ANSI.sub("", texto)


def decodificar(bruto):
    """Bytes de uma linha -> texto. Byte inválido vira U+FFFD em vez de derrubar o script."""
    return bruto.decode("utf-8", errors="replace").rstrip("\r\n")


class Acumulador:
    """Junta bytes que chegam em pedaços e devolve apenas linhas completas."""

    def __init__(self):
        self._buf = bytearray()

    def alimentar(self, dados):
        self._buf.extend(dados)
        linhas = []
        while True:
            i = self._buf.find(b"\n")
            if i < 0:
                break
            linhas.append(bytes(self._buf[: i + 1]))
            del self._buf[: i + 1]
        return linhas

    def resto(self):
        """Bytes de uma linha ainda incompleta (sem quebra de linha)."""
        resto = bytes(self._buf)
        self._buf.clear()
        return resto


def abrir_porta(porta, baud, dtr_rts_padrao=False, timeout=1.0):
    """Abre a porta. Aceita "COM11", "/dev/ttyUSB0" ou URLs do pyserial (ex.: "loop://")."""
    ser = serial.serial_for_url(porta, baudrate=baud, timeout=timeout, do_not_open=True)
    if not dtr_rts_padrao:
        ser.dtr = False
        ser.rts = False
    ser.open()
    return ser


def processar_porta(ser, emitir, acumulador, manter_cor, deve_parar):
    """Lê a porta até `deve_parar()` ser verdadeiro, chamando `emitir(texto)` por linha."""
    while not deve_parar():
        dados = ser.read(ser.in_waiting or 1)
        if not dados:
            continue
        for bruto in acumulador.alimentar(dados):
            texto = decodificar(bruto)
            if not manter_cor:
                texto = remover_ansi(texto)
            emitir(texto)


def executar(porta, baud, saida, dtr_rts_padrao, manter_cor, espera_s, max_segundos):
    caminho = Path(saida)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    inicio = time.monotonic()
    acumulador = Acumulador()

    def esgotou():
        return max_segundos is not None and time.monotonic() - inicio >= max_segundos

    with open(caminho, "a", encoding="utf-8", buffering=1) as arquivo:

        def emitir(texto):
            linha = f"{carimbo()} | {texto}"
            arquivo.write(linha + "\n")
            print(linha, flush=True)

        while not esgotou():
            try:
                ser = abrir_porta(porta, baud, dtr_rts_padrao)
            except (serial.SerialException, OSError) as erro:
                emitir(f"[logger] porta indisponível ({erro}); nova tentativa em {espera_s:g}s")
                time.sleep(espera_s)
                continue

            emitir(f"[logger] conectado em {porta} @ {baud}")
            try:
                processar_porta(ser, emitir, acumulador, manter_cor, esgotou)
            except (serial.SerialException, OSError) as erro:
                emitir(f"[logger] conexão perdida ({erro}); reconectando")
            finally:
                resto = acumulador.resto()
                if resto:
                    emitir(decodificar(resto) + " [linha incompleta]")
                ser.close()

        emitir("[logger] encerrado")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Logger de porta serial com timestamp e reconexão.")
    ap.add_argument("--porta", required=True, help="ex.: COM11 ou /dev/ttyUSB0")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--saida", help="arquivo de log (padrão: logs/serial_AAAAMMDD_HHMMSS.log)")
    ap.add_argument(
        "--dtr-rts-padrao", action="store_true", help="não zerar DTR/RTS ao abrir (pode resetar placas ESP32)"
    )
    ap.add_argument("--manter-cor", action="store_true", help="não remover códigos ANSI de cor")
    ap.add_argument("--espera", type=float, default=2.0, help="segundos entre tentativas de reconexão")
    ap.add_argument("--max-segundos", type=float, help="encerra sozinho após N segundos")
    args = ap.parse_args(argv)

    saida = args.saida or f"logs/serial_{datetime.now():%Y%m%d_%H%M%S}.log"
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")  # console cp1252 não imprime U+FFFD
    try:
        executar(args.porta, args.baud, saida, args.dtr_rts_padrao, args.manter_cor, args.espera, args.max_segundos)
    except KeyboardInterrupt:
        print("\n[logger] interrompido")
    return 0


if __name__ == "__main__":
    sys.exit(main())
