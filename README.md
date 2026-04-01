# Backtest de Transiciones de Regimen con HMM + Wavelets

Este proyecto contiene un script de backtest que detecta cambios de regimen de mercado en series temporales de Forex usando:

- Features de precio y volumen
- Volatilidad multiescala mediante wavelets
- Un modelo Hidden Markov Model (HMM)
- Esquema walk-forward (reentrenamiento periodico)

El script principal de generacion de señales es [WH_señales_backtest.py](WH_señales_backtest.py).
La ejecucion de operaciones para backtest en MT5 se realiza con el Expert Advisor [backtest.mq5](backtest.mq5).

## Flujo completo (Python + MT5)

El proyecto funciona en dos etapas:

1. [WH_señales_backtest.py](WH_señales_backtest.py)
  - genera señales de compra/venta a partir de HMM + wavelets
  - exporta el archivo de señales en formato CSV con extension .txt
2. [backtest.mq5](backtest.mq5)
  - lee el archivo de señales desde Terminal/Common/Files
  - valida señales por vela (sin duplicados)
  - ejecuta ordenes con SL/TP dinamico por ATR
  - calcula lotaje por riesgo porcentual

Este enfoque muestra un pipeline aplicado de ML a trading: modelado estadistico en Python y ejecucion/simulacion en plataforma de trading.

## Que hace el script

[WH_señales_backtest.py](WH_señales_backtest.py) ejecuta el siguiente flujo:

1. Se conecta a MetaTrader 5.
2. Descarga historico de velas del simbolo configurado.
3. Calcula features base:
   - returns y log_returns
   - volatilidad rolling
   - rango relativo (high-low)/close
   - autocorrelacion corta
   - momentum
4. Calcula features de tendencia y wavelet:
   - medias moviles rapida/lenta
   - fuerza de tendencia
   - ratio de volumen
   - wavelet_vol y noise_level
5. Entrena un HMM gaussiano con 3 estados (fijos por configuracion).
6. Etiqueta estados en terminos de:
   - CONSOLIDACION
   - TENDENCIA_ALCISTA
   - TENDENCIA_BAJISTA
7. Recorre los datos de test por bloques (walk-forward) para detectar transiciones de consolidacion a tendencia.
8. Filtra señales por:
   - confirmacion de consolidacion previa
   - incremento de volatilidad
   - direccion minima de precio
   - cooldown temporal entre señales
9. Exporta las señales a archivo CSV con nombre tipo:
   - WAVELET_HMM_USDJPY.txt

## Estructura de salida

El archivo de salida contiene columnas como:

- timestamp
- valid_for_time
- price
- regime
- regime_state
- strategy_used
- signal (1 compra, -1 venta)
- volatility
- noise_level
- trend_deviation

Este archivo es el input operativo del EA en [backtest.mq5](backtest.mq5).

## Componente MQL5 (backtest y ejecucion)

El EA [backtest.mq5](backtest.mq5) hace lo siguiente:

- Lee señales desde Inp_SignalsFilename (por defecto WAVELET_HMM_USDJPY.txt)
- Procesa solo en apertura de nueva vela
- Evita reprocesar señales ya ejecutadas (ID unico por señal)
- Mantiene una sola posicion abierta por simbolo/magic number
- Calcula Stop Loss y Take Profit usando ATR (metodo configurable)
- Calcula tamaño de lote por riesgo (Inp_RiskPercent)
- Ejecuta BUY/SELL segun el campo signal del archivo

Inputs principales del EA:

- Inp_SignalsFilename
- Inp_RiskPercent
- Inp_MagicNumber
- Inp_SL_ATR_Multiplier
- Inp_TP_ATR_Multiplier
- Inp_EnableDebug

## Requisitos

Depencias usadas en el script (versiones fijadas en [requirements.txt](requirements.txt)):

- MetaTrader5==5.0.5640
- pandas==2.3.0
- numpy==1.26.4
- hmmlearn==0.3.2
- scikit-learn==1.5.2
- PyWavelets==1.9.0

Adicionalmente necesitas:

- Python 3.10+ recomendado
- Terminal de MetaTrader 5 instalado y funcionando
- Credenciales validas de cuenta demo/real en MT5
- El simbolo configurado debe estar habilitado en Market Watch

## Instalacion

```bash
pip install -r requirements.txt
```

## Configuracion rapida

En [WH_señales_backtest.py](WH_señales_backtest.py) ajusta al menos:

- Conexion MT5:
  - account
  - password
  - server
- Instrumento y marco temporal:
  - SYMBOL
  - TIMEFRAME
- Ventanas de entrenamiento:
  - TRAIN_WINDOW
  - RETRAIN_EVERY
- Sensibilidad de señales:
  - CONSOLIDATION_REQUIRED
  - VOL_INCREASE_MULT
  - MIN_PRICE_MOVE
  - COOLDOWN_HOURS
- Configuracion wavelet:
  - WAVELET
  - WAVELET_LEVEL
  - WAVELET_WINDOW

## Ejecucion

```bash
python WH_señales_backtest.py
```

Luego, para correr el backtest en MT5:

1. Copia el archivo de señales generado a Terminal/Common/Files.
2. Compila y adjunta [backtest.mq5](backtest.mq5) en el Strategy Tester.
3. Asegura que Inp_SignalsFilename coincida con el nombre del archivo exportado.
4. Ejecuta el test en el mismo simbolo/timeframe usado al generar señales.

Durante la ejecucion veras logs de:

- estado de conexion a MT5
- tamano de ventanas train/test
- entrenamiento de HMM
- clasificacion de estados
- señales generadas
- tiempo total de ejecucion

## Logica de señal (resumen)

Se emite señal cuando se detecta salida de consolidacion hacia tendencia:

- Consolidacion previa en velas recientes
- Estado actual etiquetado como tendencia alcista o bajista
- Aumento de wavelet_vol frente a velas previas
- Confirmacion de movimiento en precio
- Respeto del cooldown entre señales

Mapeo de estrategia:

- TENDENCIA_ALCISTA -> BREAKOUT_BULL -> signal = 1
- TENDENCIA_BAJISTA -> BREAKOUT_BEAR -> signal = -1

## Metricas del backtest

Resultados agregados obtenidos en el backtest:

- Periodo aproximado evaluado: 8 años
- Total de operaciones: 446
- Profit Factor: 1.62
- Drawdown maximo: 19%
- Relacion riesgo/beneficio objetivo: 1:3
- Win rate: 33.63%

Lectura rapida de las metricas:

- Un Profit Factor mayor a 1 (1.62) sugiere ventaja estadistica positiva.
- Un drawdown de 19% indica riesgo moderado que debe gestionarse con control de lotaje.
- Con un ratio 1:3, un win rate de 33.63% nos da una ventaja de 8.63% sobre el 25% de win rate que nos dejaría "tablas".


