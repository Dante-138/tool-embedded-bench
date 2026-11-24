"""Grava mensagens MQTT em CSV ou JSONL, com timestamp local e flag de retain.

Uso:
    python bancada/mqtt_logger.py --broker broker.exemplo.com --topico "sensores/#" --saida logs/mqtt.csv
    python bancada/mqtt_logger.py --broker broker.exemplo.com --porta 8883 --tls \\
        --topico a/b --topico c/d --saida logs/mqtt.jsonl --max-segundos 600

Formato de saída pela extensão: `.csv` grava CSV; qualquer outra grava JSONL
(um objeto JSON por linha, com o campo `json` quando o payload é JSON válido).

A coluna `retain` importa: mensagem com retain=1 é uma cópia guardada pelo
broker e entregue na hora da assinatura. Ela pode ser antiga, mesmo chegando
"agora" (MQTT-3.3.1-8/9). Sem essa coluna, um snapshot velho parece leitura viva.

Credenciais: nunca pela linha de comando (ficam no histórico do shell). Use as
variáveis de ambiente MQTT_USUARIO e MQTT_SENHA.
"""

import argparse
import csv
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import paho.mqtt.client as mqtt

CAMPOS_CSV = ["timestamp", "topico", "qos", "retain", "binario", "payload"]


def decodificar_payload(payload):
    """Retorna (texto, binario). UTF-8 quando possível; senão o payload em hexadecimal."""
    try:
        return payload.decode("utf-8"), False
    except UnicodeDecodeError:
        return payload.hex(), True


def montar_registro(msg, agora=None):
    agora = agora or datetime.now()
    texto, binario = decodificar_payload(bytes(msg.payload))
    registro = {
        "timestamp": agora.isoformat(timespec="milliseconds"),
        "topico": msg.topic,
        "qos": msg.qos,
        "retain": bool(msg.retain),
        "binario": binario,
        "payload": texto,
    }
    if not binario:
        try:
            registro["json"] = json.loads(texto)
        except ValueError:
            pass
    return registro


class Gravador:
    def __init__(self, caminho):
        self.caminho = Path(caminho)
        self.caminho.parent.mkdir(parents=True, exist_ok=True)
        self.csv = self.caminho.suffix.lower() == ".csv"
        novo = not self.caminho.exists() or self.caminho.stat().st_size == 0
        self._arq = open(self.caminho, "a", encoding="utf-8", newline="")
        if self.csv:
            self._csv = csv.DictWriter(self._arq, fieldnames=CAMPOS_CSV, extrasaction="ignore")
            if novo:
                self._csv.writeheader()

    def escrever(self, registro):
        if self.csv:
            self._csv.writerow(registro)
        else:
            self._arq.write(json.dumps(registro, ensure_ascii=False) + "\n")
        self._arq.flush()

    def fechar(self):
        self._arq.close()


def criar_cliente():
    """Compatível com paho-mqtt 1.x e 2.x (a 2.x exige a versão da API de callbacks)."""
    if hasattr(mqtt, "CallbackAPIVersion"):
        return mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    return mqtt.Client()


def conexao_falhou(codigo):
    """`codigo` é ReasonCode na paho 2.x e int na 1.x."""
    falhou = getattr(codigo, "is_failure", None)
    return bool(falhou) if falhou is not None else codigo != 0


def executar(args):
    gravador = Gravador(args.saida)
    cliente = criar_cliente()

    usuario = os.environ.get("MQTT_USUARIO")
    if usuario:
        cliente.username_pw_set(usuario, os.environ.get("MQTT_SENHA"))
    if args.tls:
        cliente.tls_set()  # valida o certificado do broker com as CAs do sistema
    cliente.reconnect_delay_set(min_delay=1, max_delay=30)

    def ao_conectar(client, userdata, flags, codigo, properties=None):
        if conexao_falhou(codigo):
            print(f"[mqtt] conexão recusada: {codigo}", flush=True)
            return
        print(f"[mqtt] conectado em {args.broker}:{args.porta}", flush=True)
        for topico in args.topico:  # reassina a cada (re)conexão
            client.subscribe(topico, qos=args.qos)

    def ao_receber(client, userdata, msg):
        registro = montar_registro(msg)
        gravador.escrever(registro)
        marca = " [retain]" if registro["retain"] else ""
        print(f"{registro['timestamp']} {registro['topico']}{marca}: {registro['payload'][:120]}", flush=True)

    cliente.on_connect = ao_conectar
    cliente.on_message = ao_receber
    cliente.connect_async(args.broker, args.porta, keepalive=60)
    cliente.loop_start()
    try:
        fim = None if args.max_segundos is None else time.monotonic() + args.max_segundos
        while fim is None or time.monotonic() < fim:
            time.sleep(0.2)
    except KeyboardInterrupt:
        print("\n[mqtt] interrompido")
    finally:
        cliente.loop_stop()
        cliente.disconnect()
        gravador.fechar()


def main(argv=None):
    ap = argparse.ArgumentParser(description="Grava mensagens MQTT em CSV/JSONL.")
    ap.add_argument("--broker", required=True)
    ap.add_argument("--porta", type=int, default=1883)
    ap.add_argument("--tls", action="store_true", help="conexão TLS (normalmente porta 8883)")
    ap.add_argument(
        "--topico", action="append", required=True, help="tópico a assinar; pode repetir. Evite '#' em broker público"
    )
    ap.add_argument("--qos", type=int, choices=(0, 1, 2), default=0)
    ap.add_argument("--saida", default=f"logs/mqtt_{datetime.now():%Y%m%d_%H%M%S}.jsonl")
    ap.add_argument("--max-segundos", type=float, help="encerra sozinho após N segundos")
    args = ap.parse_args(argv)

    if "#" in args.topico:
        print("[aviso] '#' recebe todo o tráfego do broker, inclusive de terceiros.", file=sys.stderr)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    executar(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
