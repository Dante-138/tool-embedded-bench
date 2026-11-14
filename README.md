# tool-embedded-bench

Ferramentas em Python para bancada de eletrônica e para sistemas embarcados e IoT: captura de log serial e MQTT, cálculos de hardware, rádio (LoRa e BLE) e análise de dados de sensor. Cada script é independente, roda pela linha de comando e tem testes.

Nasceram do trabalho com firmware (ESP32, nRF), LoRaWAN e beacons BLE. Os valores de exemplo são genéricos: nenhum identificador, credencial ou parâmetro de rede de produto real está neste repositório.

## Estrutura

| Pasta | Script | O que faz |
|---|---|---|
| `bancada/` | `serial_logger.py` | Lê a porta serial com timestamp em milissegundos, remove cores ANSI e reconecta sozinho se a placa reiniciar ou o USB cair. Não precisa de terminal interativo (o `idf.py monitor` precisa). |
| | `mqtt_logger.py` | Assina tópicos e grava em CSV ou JSONL, com a flag `retain`, que separa mensagem viva de snapshot guardado pelo broker. Credenciais só por variável de ambiente. |
| `hardware/` | `battery_life.py` | Autonomia de bateria por perfil de fases (duty-cycle), com autodescarga e a participação de cada fase no consumo. |
| | `divisor_tensao.py` | Divisor resistivo: tensão de saída, pior caso por tolerância, escolha de R1/R2 nas séries E12/E24 e leitura de ADC. |
| | `crc.py` | CRC de 8, 16 e 32 bits pelo modelo Rocksoft (Modbus, CCITT, XMODEM, Kermit, CRC-32, CRC-32C e outros). |
| `radio/` | `lora_airtime.py` | Tempo no ar LoRa pela fórmula da Semtech, com LDRO automático, overhead LoRaWAN e intervalo mínimo por duty cycle. |
| | `lora_link_budget.py` | Margem de RSSI e de SNR por SF (a menor delas limita o link) e alcance teórico em espaço livre. |
| | `ble_advertising.py` | Decodifica advertising BLE: estruturas AD, iBeacon e Eddystone (UID, URL e TLM). |
| `dados/` | `filtro_temperatura.py` | Filtro do firmware (média aparada e EMA) portado para Python, mais EMA, outliers e gráfico sobre uma coluna de CSV. |

## Como usar

Requer Python 3.10 ou superior (testado na 3.13).

```
pip install -r requirements.txt
python -m unittest
```

Exemplos:

```
python bancada/serial_logger.py --porta COM11 --saida logs/teste.log
python hardware/battery_life.py --capacidade 2000 --fase tx:120:8 --fase escuta:25:12 --fase sleep:0.05:580
python hardware/crc.py --algoritmo crc16-modbus --hex "01 03 00 00 00 0A"
python radio/lora_airtime.py --payload 10 --lorawan --duty-cycle 1
python radio/lora_link_budget.py avaliar --rssi -98 --snr -3 --sf 7
python dados/filtro_temperatura.py leituras.csv --coluna temperatura --sep ";" --decimal ","
```

Todo script aceita `--help`.

## Como foi validado

- 144 testes com `unittest`, sem dependência extra, rodando com todo aviso tratado como erro.
- Referências independentes, para não testar o código só contra ele mesmo:
  - CRC: valores do catálogo de CRCs para `123456789`, comparação com `zlib.crc32` e `binascii.crc_hqx`, e um quadro Modbus real (`01 03 00 00 00 0A` termina em `C5 CD`).
  - Tempo no ar LoRa: 41,2 ms (SF7) e 991,2 ms (SF12) para 10 bytes de payload PHY, e 61,7 ms e 1482,8 ms com o overhead LoRaWAN, os valores dos calculadores públicos de airtime.
  - BLE: quadros de exemplo de iBeacon e Eddystone montados byte a byte.

## Limitações conhecidas

- `serial_logger.py` foi testado com o loopback do pyserial (`loop://`), não com uma placa física. Abrir a porta pode resetar placas ESP32 conforme o driver; por isso o padrão zera DTR/RTS, o que não garante nada em todos os drivers.
- `mqtt_logger.py` foi testado no registro, na gravação e na criação do cliente. A conexão com um broker real não foi exercitada nos testes.
- `lora_link_budget.py` usa sensibilidade e SNR mínimo típicos da família SX127x. São valores de referência, não garantidos: confira o datasheet do seu rádio. O alcance em espaço livre é um limite otimista.
- `filtro_temperatura.py` marca outliers na série inteira. Para séries longas com deriva lenta, uma janela deslizante seria mais adequada.
- Estimativa de distância por RSSI (BLE) é grosseira: varia com corpo, paredes, antena e canal.
