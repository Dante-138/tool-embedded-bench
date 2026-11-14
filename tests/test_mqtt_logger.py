import contextlib
import csv
import io
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from bancada import mqtt_logger as m

AGORA = datetime(2026, 9, 29, 14, 3, 7, 412_000)


def mensagem(topico="sensores/a", payload=b"21.5", qos=1, retain=False):
    return SimpleNamespace(topic=topico, payload=payload, qos=qos, retain=retain)


class TestRegistro(unittest.TestCase):
    def test_texto_simples(self):
        r = m.montar_registro(mensagem(), AGORA)
        self.assertEqual(r["timestamp"], "2026-09-29T14:03:07.412")
        self.assertEqual((r["topico"], r["qos"], r["retain"], r["binario"], r["payload"]),
                         ("sensores/a", 1, False, False, "21.5"))
        self.assertEqual(r["json"], 21.5)  # "21.5" também é JSON válido

    def test_payload_json_vira_objeto(self):
        r = m.montar_registro(mensagem(payload=b'{"t": 21.5, "bat": 87}'), AGORA)
        self.assertEqual(r["json"], {"t": 21.5, "bat": 87})

    def test_payload_que_nao_e_json_nao_tem_campo_json(self):
        r = m.montar_registro(mensagem(payload=b"online"), AGORA)
        self.assertNotIn("json", r)
        self.assertEqual(r["payload"], "online")

    def test_payload_binario_vira_hexadecimal(self):
        r = m.montar_registro(mensagem(payload=b"\xff\x00\x10"), AGORA)
        self.assertTrue(r["binario"])
        self.assertEqual(r["payload"], "ff0010")
        self.assertNotIn("json", r)

    def test_retain_e_registrado_como_booleano(self):
        self.assertIs(m.montar_registro(mensagem(retain=1), AGORA)["retain"], True)
        self.assertIs(m.montar_registro(mensagem(retain=0), AGORA)["retain"], False)

    def test_payload_vazio(self):
        r = m.montar_registro(mensagem(payload=b""), AGORA)
        self.assertEqual(r["payload"], "")
        self.assertFalse(r["binario"])


class TestGravador(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def test_csv_com_virgula_e_quebra_de_linha_no_payload(self):
        caminho = self.dir / "sub" / "log.csv"
        g = m.Gravador(caminho)
        g.escrever(m.montar_registro(mensagem(payload=b"a,b\nc"), AGORA))
        g.escrever(m.montar_registro(mensagem(topico="x/y", payload=b"ok", retain=True), AGORA))
        g.fechar()
        with open(caminho, encoding="utf-8", newline="") as f:
            linhas = list(csv.DictReader(f))
        self.assertEqual(len(linhas), 2)
        self.assertEqual(linhas[0]["payload"], "a,b\nc")
        self.assertEqual(linhas[1]["retain"], "True")
        self.assertNotIn("json", linhas[0])  # CSV só grava as colunas fixas

    def test_csv_reaberto_nao_repete_o_cabecalho(self):
        caminho = self.dir / "log.csv"
        for _ in range(2):
            g = m.Gravador(caminho)
            g.escrever(m.montar_registro(mensagem(), AGORA))
            g.fechar()
        texto = caminho.read_text(encoding="utf-8")
        self.assertEqual(texto.count("timestamp,topico"), 1)
        self.assertEqual(len(texto.strip().splitlines()), 3)

    def test_jsonl_com_acentos_e_campo_json(self):
        caminho = self.dir / "log.jsonl"
        g = m.Gravador(caminho)
        g.escrever(m.montar_registro(mensagem(payload='{"nome": "ação"}'.encode("utf-8")), AGORA))
        g.fechar()
        bruto = caminho.read_text(encoding="utf-8")
        self.assertIn("ação", bruto)  # ensure_ascii=False
        registro = json.loads(bruto.splitlines()[0])
        self.assertEqual(registro["json"], {"nome": "ação"})


class TestCliente(unittest.TestCase):
    def test_cria_cliente_sem_tocar_a_rede(self):
        cliente = m.criar_cliente()
        self.assertTrue(callable(cliente.subscribe))
        self.assertTrue(callable(cliente.connect_async))

    def test_conexao_falhou_aceita_int_e_reason_code(self):
        self.assertFalse(m.conexao_falhou(0))
        self.assertTrue(m.conexao_falhou(5))
        self.assertFalse(m.conexao_falhou(SimpleNamespace(is_failure=False)))
        self.assertTrue(m.conexao_falhou(SimpleNamespace(is_failure=True)))

    def test_cli_exige_broker_e_topico(self):
        with contextlib.redirect_stderr(io.StringIO()):
            for argv in ([], ["--broker", "x"], ["--topico", "a"]):
                with self.subTest(argv=argv), self.assertRaises(SystemExit):
                    m.main(argv)


if __name__ == "__main__":
    unittest.main()
