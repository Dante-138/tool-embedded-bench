import contextlib
import io
import math
import unittest

from hardware import divisor_tensao as m


class TestParseResistencia(unittest.TestCase):
    def test_formatos(self):
        casos = {
            "470": 470.0,
            "100k": 100_000.0,
            "100K": 100_000.0,
            "4.7k": 4700.0,
            "4k7": 4700.0,
            "2R2": 2.2,
            "1M": 1_000_000.0,
            "1M5": 1_500_000.0,
        }
        for texto, esperado in casos.items():
            with self.subTest(texto=texto):
                self.assertAlmostEqual(m.parse_resistencia(texto), esperado)

    def test_invalidos(self):
        for texto in ("", "abc", "10m", "k7", "1.2.3k"):
            with self.subTest(texto=texto), self.assertRaises(ValueError):
                m.parse_resistencia(texto)

    def test_formatar_e_voltar(self):
        for valor in (470.0, 4700.0, 100_000.0, 1_500_000.0):
            with self.subTest(valor=valor):
                self.assertAlmostEqual(m.parse_resistencia(m.formatar_resistencia(valor)), valor)


class TestDivisor(unittest.TestCase):
    def test_saida(self):
        self.assertAlmostEqual(m.tensao_saida(4.2, 100_000, 100_000), 2.1)
        self.assertAlmostEqual(m.tensao_saida(10, 10_000, 5_000), 10 / 3)

    def test_inversa(self):
        vout = m.tensao_saida(4.2, 220_000, 100_000)
        self.assertAlmostEqual(m.vin_a_partir_da_saida(vout, 220_000, 100_000), 4.2)

    def test_corrente_do_divisor(self):
        # 4,2 V sobre 200 kohm = 21 uA
        self.assertAlmostEqual(m.corrente_divisor_ua(4.2, 100_000, 100_000), 21.0)

    def test_pior_caso_envolve_o_valor_nominal(self):
        nominal = m.tensao_saida(4.2, 100_000, 100_000)
        vmin, vmax = m.tolerancia_pior_caso(4.2, 100_000, 100_000, 1.0)
        self.assertLess(vmin, nominal)
        self.assertGreater(vmax, nominal)

    def test_pior_caso_de_1_por_cento_em_divisor_igual(self):
        # Razão vai de 0,99/(1,01+0,99) a 1,01/(0,99+1,01): 0,495 a 0,505.
        vmin, vmax = m.tolerancia_pior_caso(4.2, 100_000, 100_000, 1.0)
        self.assertAlmostEqual(vmin, 4.2 * 0.495)
        self.assertAlmostEqual(vmax, 4.2 * 0.505)

    def test_tolerancia_zero_da_o_nominal(self):
        vmin, vmax = m.tolerancia_pior_caso(4.2, 100_000, 47_000, 0.0)
        self.assertAlmostEqual(vmin, vmax)
        self.assertAlmostEqual(vmin, m.tensao_saida(4.2, 100_000, 47_000))


class TestADC(unittest.TestCase):
    def test_contagens(self):
        self.assertEqual(m.contagens_adc(0, 3.3, 12), 0)
        self.assertEqual(m.contagens_adc(3.3, 3.3, 12), 4095)
        self.assertEqual(m.contagens_adc(5.0, 3.3, 12), 4095)  # satura no fundo de escala

    def test_ida_e_volta(self):
        vin = 3.9
        cont = m.contagens_adc(m.tensao_saida(vin, 100_000, 100_000), 3.3, 12)
        self.assertAlmostEqual(m.vin_de_contagens(cont, 100_000, 100_000, 3.3, 12), vin, delta=0.005)


class TestSeriesEProjeto(unittest.TestCase):
    def test_series(self):
        self.assertEqual(len(m.SERIES["e12"]), 12)
        self.assertEqual(len(m.SERIES["e24"]), 24)
        for serie, base in m.SERIES.items():
            self.assertEqual(base, sorted(base), serie)

    def test_valores_da_serie_cobrem_de_10_ohm_a_mais_de_9_megaohm(self):
        valores = m.valores_da_serie("e24")
        self.assertEqual(valores[0], 10.0)
        self.assertEqual(valores[-1], 9_100_000.0)
        self.assertIn(4700.0, valores)
        self.assertIn(220_000.0, valores)

    def test_projeto_de_divisor_por_2_acha_par_igual_e_prefere_resistencia_alta(self):
        melhores = m.projetar(4.2, 2.1, rtotal_min=100_000, rtotal_max=2_000_000)
        primeiro = melhores[0]
        self.assertEqual(primeiro["r1"], primeiro["r2"])
        self.assertAlmostEqual(primeiro["erro_pct"], 0.0, places=6)
        self.assertEqual(primeiro["r1"] + primeiro["r2"], 2_000_000)  # desempate: menor consumo

    def test_projeto_respeita_limites_e_a_serie(self):
        valores = set(m.valores_da_serie("e24"))
        for r in m.projetar(5.0, 3.3, rtotal_min=50_000, rtotal_max=500_000, quantos=10):
            self.assertIn(r["r1"], valores)
            self.assertIn(r["r2"], valores)
            self.assertTrue(50_000 <= r["r1"] + r["r2"] <= 500_000)
            self.assertLess(r["erro_pct"], 1.0)

    def test_resultados_ordenados_por_erro(self):
        erros = [r["erro_pct"] for r in m.projetar(5.0, 3.3, quantos=10)]
        self.assertEqual(erros, sorted(erros))

    def test_sem_par_dentro_dos_limites(self):
        self.assertEqual(m.projetar(4.2, 2.1, rtotal_min=1e9, rtotal_max=math.inf), [])


class TestCLI(unittest.TestCase):
    def rodar(self, argv):
        saida = io.StringIO()
        with contextlib.redirect_stdout(saida):
            codigo = m.main(argv)
        return codigo, saida.getvalue()

    def test_saida_com_tolerancia(self):
        codigo, texto = self.rodar(["saida", "--vin", "4.2", "--r1", "100k", "--r2", "100k", "--tol", "1"])
        self.assertEqual(codigo, 0)
        self.assertIn("2.1000 V", texto)
        self.assertIn("2.0790 V a 2.1210 V", texto)

    def test_projetar(self):
        codigo, texto = self.rodar(
            ["projetar", "--vin-max", "4.2", "--vout", "2.1", "--rtotal-min", "200k", "--rtotal-max", "2M"]
        )
        self.assertEqual(codigo, 0)
        self.assertIn("1M", texto)

    def test_adc(self):
        codigo, texto = self.rodar(["adc", "--contagens", "2048", "--r1", "100k", "--r2", "100k", "--vref", "3.3"])
        self.assertEqual(codigo, 0)
        self.assertIn("V (2048 contagens de 4095)", texto)


if __name__ == "__main__":
    unittest.main()
