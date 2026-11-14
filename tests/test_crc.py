import binascii
import contextlib
import io
import unittest
import zlib

from hardware import crc as m

# Valor de verificação do catálogo de CRCs: CRC de b"123456789".
VERIFICACAO = {
    "crc8": 0xF4,
    "crc8-maxim": 0xA1,
    "crc16-ccitt-false": 0x29B1,
    "crc16-xmodem": 0x31C3,
    "crc16-kermit": 0x2189,
    "crc16-modbus": 0x4B37,
    "crc16-arc": 0xBB3D,
    "crc32": 0xCBF43926,
    "crc32c": 0xE3069283,
    "crc32-mpeg2": 0x0376E6E7,
}

DADOS = bytes(range(256)) * 3 + b"embedded bench"


class TestCRC(unittest.TestCase):
    def test_valores_de_verificacao_do_catalogo(self):
        for nome, esperado in VERIFICACAO.items():
            with self.subTest(algoritmo=nome):
                self.assertEqual(m.crc(b"123456789", nome), esperado)

    def test_todo_algoritmo_tem_valor_de_verificacao(self):
        self.assertEqual(set(VERIFICACAO), set(m.ALGORITMOS))

    def test_crc32_bate_com_zlib(self):
        self.assertEqual(m.crc(DADOS, "crc32"), zlib.crc32(DADOS))
        self.assertEqual(m.crc(b"", "crc32"), zlib.crc32(b""))

    def test_crc16_bate_com_binascii(self):
        self.assertEqual(m.crc(DADOS, "crc16-xmodem"), binascii.crc_hqx(DADOS, 0x0000))
        self.assertEqual(m.crc(DADOS, "crc16-ccitt-false"), binascii.crc_hqx(DADOS, 0xFFFF))

    def test_quadro_modbus_conhecido(self):
        # Leitura de 10 registradores a partir do 0 no escravo 1: CRC 0xCDC5, enviado C5 CD.
        quadro = bytes.fromhex("01 03 00 00 00 0A")
        self.assertEqual(m.crc(quadro, "crc16-modbus"), 0xCDC5)

    def test_crc_do_quadro_com_crc_anexado_e_zero_no_modbus(self):
        quadro = bytes.fromhex("01 03 00 00 00 0A C5 CD")
        self.assertEqual(m.crc(quadro, "crc16-modbus"), 0)

    def test_largura_menor_que_8_e_recusada(self):
        with self.assertRaises(ValueError):
            m.calcular(b"a", m.ParametrosCRC(4, 0x3, 0, False, False, 0))

    def test_hex_para_bytes_aceita_formatos_comuns(self):
        esperado = b"\x01\x03\xff"
        for texto in ("01 03 FF", "0x01,0x03,0xFF", "01:03:ff", "0103ff"):
            with self.subTest(texto=texto):
                self.assertEqual(m.hex_para_bytes(texto), esperado)

    def test_cli_imprime_crc_e_ordem_dos_bytes(self):
        saida = io.StringIO()
        with contextlib.redirect_stdout(saida):
            codigo = m.main(["--algoritmo", "crc16-modbus", "--hex", "01 03 00 00 00 0A"])
        self.assertEqual(codigo, 0)
        texto = saida.getvalue()
        self.assertIn("0xCDC5", texto)
        self.assertIn("C5 CD", texto)  # little-endian, como vai no fio do Modbus

    def test_cli_hex_invalido_retorna_erro(self):
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(m.main(["--algoritmo", "crc8", "--hex", "zz"]), 2)


if __name__ == "__main__":
    unittest.main()
