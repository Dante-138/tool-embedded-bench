import contextlib
import io
import re
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

import serial

from bancada import serial_logger as m

PADRAO_LINHA = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3} \| (.*)$")


class TestTexto(unittest.TestCase):
    def test_carimbo_com_milissegundos(self):
        self.assertEqual(m.carimbo(datetime(2026, 9, 29, 14, 3, 7, 412_999)), "2026-09-29 14:03:07.412")

    def test_remover_ansi(self):
        self.assertEqual(m.remover_ansi("\x1b[0;32mI (12) TAG: ok\x1b[0m"), "I (12) TAG: ok")

    def test_decodificar_nao_quebra_com_byte_invalido(self):
        self.assertEqual(m.decodificar(b"ok \xff\xfe fim\r\n"), "ok �� fim")

    def test_decodificar_utf8(self):
        self.assertEqual(m.decodificar("conexão\r\n".encode("utf-8")), "conexão")


class TestAcumulador(unittest.TestCase):
    def test_junta_pedacos_e_devolve_so_linhas_completas(self):
        a = m.Acumulador()
        self.assertEqual(a.alimentar(b"lin"), [])
        self.assertEqual(a.alimentar(b"ha 1\r\nlinha 2\r\npar"), [b"linha 1\r\n", b"linha 2\r\n"])
        self.assertEqual(a.resto(), b"par")
        self.assertEqual(a.resto(), b"")  # resto() esvazia o buffer

    def test_varias_linhas_de_uma_vez(self):
        self.assertEqual(m.Acumulador().alimentar(b"a\nb\nc\n"), [b"a\n", b"b\n", b"c\n"])


class TestPorta(unittest.TestCase):
    def test_abrir_sem_reset_zera_dtr_e_rts(self):
        with contextlib.closing(m.abrir_porta("loop://", 115200)) as ser:
            self.assertTrue(ser.is_open)
            self.assertFalse(ser.dtr)
            self.assertFalse(ser.rts)

    def test_abrir_com_padrao_do_driver_mantem_dtr_e_rts_ativos(self):
        with contextlib.closing(m.abrir_porta("loop://", 115200, dtr_rts_padrao=True)) as ser:
            self.assertTrue(ser.dtr)
            self.assertTrue(ser.rts)

    def test_porta_inexistente_levanta_serial_exception(self):
        with self.assertRaises(serial.SerialException):
            m.abrir_porta("COM_INEXISTENTE_99", 115200)

    def test_processar_porta_emite_linhas_completas_sem_cor(self):
        with contextlib.closing(serial.serial_for_url("loop://", timeout=0.05)) as ser:
            ser.write(b"linha 1\r\n\x1b[0;32mI (12) TAG: ok\x1b[0m\r\nparcial")
            acumulador, emitidas, chamadas = m.Acumulador(), [], {"n": 0}

            def parar():
                chamadas["n"] += 1
                return chamadas["n"] > 3

            m.processar_porta(ser, emitidas.append, acumulador, manter_cor=False, deve_parar=parar)
        self.assertEqual(emitidas, ["linha 1", "I (12) TAG: ok"])
        self.assertEqual(acumulador.resto(), b"parcial")

    def test_processar_porta_pode_manter_a_cor(self):
        with contextlib.closing(serial.serial_for_url("loop://", timeout=0.05)) as ser:
            ser.write(b"\x1b[0;32mok\x1b[0m\n")
            emitidas, chamadas = [], {"n": 0}

            def parar():
                chamadas["n"] += 1
                return chamadas["n"] > 2

            m.processar_porta(ser, emitidas.append, m.Acumulador(), manter_cor=True, deve_parar=parar)
        self.assertEqual(emitidas, ["\x1b[0;32mok\x1b[0m"])


class TestExecutar(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.saida = Path(self._tmp.name) / "sub" / "teste.log"

    def executar(self, porta, max_segundos):
        with contextlib.redirect_stdout(io.StringIO()):
            m.executar(porta, 115200, self.saida, dtr_rts_padrao=False, manter_cor=False,
                       espera_s=0.1, max_segundos=max_segundos)
        linhas = self.saida.read_text(encoding="utf-8").splitlines()
        for linha in linhas:
            self.assertRegex(linha, PADRAO_LINHA)
        return [PADRAO_LINHA.match(l).group(1) for l in linhas]

    def test_conecta_grava_com_timestamp_e_encerra(self):
        mensagens = self.executar("loop://", max_segundos=0.2)
        self.assertEqual(mensagens[0], "[logger] conectado em loop:// @ 115200")
        self.assertEqual(mensagens[-1], "[logger] encerrado")

    def test_porta_indisponivel_tenta_de_novo_ate_o_fim_do_tempo(self):
        mensagens = self.executar("COM_INEXISTENTE_99", max_segundos=0.45)
        tentativas = [x for x in mensagens if "porta indisponível" in x]
        self.assertGreaterEqual(len(tentativas), 2)
        self.assertEqual(mensagens[-1], "[logger] encerrado")

    def test_cria_a_pasta_do_log_e_acrescenta_em_vez_de_sobrescrever(self):
        self.executar("loop://", max_segundos=0.1)
        primeira = self.saida.read_text(encoding="utf-8").splitlines()
        self.executar("loop://", max_segundos=0.1)
        segunda = self.saida.read_text(encoding="utf-8").splitlines()
        self.assertEqual(segunda[: len(primeira)], primeira)
        self.assertGreater(len(segunda), len(primeira))

    def test_cli_sem_porta_da_erro_de_argumento(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            m.main([])


if __name__ == "__main__":
    unittest.main()
