import MetaTrader5 as mt5 
import pandas as pd
import numpy as np
import warnings
import time
import logging
from datetime import datetime, timedelta
from hmmlearn import hmm
from sklearn.preprocessing import RobustScaler
import pywt

SYMBOL = "USDJPY"
TIMEFRAME = mt5.TIMEFRAME_H1
LOOKBACK_WINDOW = 99999  

TRAIN_WINDOW = 50000    
RETRAIN_EVERY = 10000   

CONSOLIDATION_REQUIRED = 1   
VOL_INCREASE_MULT = 0.6     
MIN_PRICE_MOVE = 0.0      
COOLDOWN_HOURS = 24        

WAVELET = 'db4'
WAVELET_LEVEL = 2
WAVELET_WINDOW = 12

HMM_N_STATES = 3 

MIN_TRAIN_ROWS = 200
OUTPUT_FILE = f'WAVELET_HMM_{SYMBOL}.txt'

np.random.seed(42)
warnings.filterwarnings("ignore")

# Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s')
logger = logging.getLogger(__name__)

"""account = 25208113  
password = "a.f^ZUB1;L?t"  
server = "Tickmill-Demo"""
"""
account = 87557416  
password = "-gL8HeRl"  
server = "MetaQuotes-Demo" 
"""
account = 104551427  
password = "4aHcEgH!"  
server = "MetaQuotes-Demo"

def connect_mt5(account=None, password=None, server=None):
    if account is None:
        if not mt5.initialize():
            raise ConnectionError(f"Error al conectar con MetaTrader 5 (initialize): {mt5.last_error()}")
    else:
        if not mt5.initialize(login=account, password=password, server=server):
            raise ConnectionError(
                f"Error al conectar con MetaTrader 5 con credenciales (login/server): {mt5.last_error()}"
            )
    
    if not mt5.terminal_info():
        raise ConnectionError(f"No se pudo obtener información del terminal: {mt5.last_error()}")
    
    logger.info(f"Conexión MT5 exitosa - Cuenta: {mt5.account_info().login}")
    logger.info(f"Servidor: {mt5.account_info().server}")
    logger.info(f"Balance: {mt5.account_info().balance}")

def get_historical_data(symbol, timeframe, n_bars):
    logger.info(f"Obteniendo {n_bars} velas de {symbol}...")
    rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, n_bars)
    if rates is None or len(rates) < 100:
        raise ValueError("Datos insuficientes de MT5")
    df = pd.DataFrame(rates)
    df['time'] = pd.to_datetime(df['time'], unit='s')
    df.set_index('time', inplace=True)
    df.rename(columns={'tick_volume': 'volume'}, inplace=True)
    logger.info(f"Descargadas {len(df)} velas")
    return df

def _wavelet_vol_from_array(arr, wavelet=WAVELET, level=WAVELET_LEVEL):
    try:
        if len(arr) < 4:
            return np.nan, np.nan
        coeffs = pywt.wavedec(arr, wavelet, level=level)
        detail_coeffs = coeffs[1:]
        detail_stds = [np.std(c) for c in detail_coeffs if len(c) > 0]
        wavelet_vol = float(np.mean(detail_stds)) if len(detail_stds) > 0 else 0.0
        noise = float(np.std(detail_coeffs[0])) if len(detail_coeffs) > 0 and len(detail_coeffs[0])>0 else 0.0
        return wavelet_vol, noise
    except Exception:
        return np.nan, np.nan

def calculate_wavelet_features_series(close_series, window=WAVELET_WINDOW, wavelet=WAVELET, level=WAVELET_LEVEL):
    logger.info(f"Calculando volatilidad wavelet (window={window}) sobre subset...")

    wavelet_vol = close_series.rolling(window=window, min_periods=window).apply(
        lambda arr: _wavelet_vol_from_array(arr, wavelet=wavelet, level=level)[0], raw=True
    )

    noise_level = close_series.rolling(window=window, min_periods=window).apply(
        lambda arr: _wavelet_vol_from_array(arr, wavelet=wavelet, level=level)[1], raw=True
    )

    return wavelet_vol, noise_level


def calculate_basic_features(df):
    df = df.copy()
    df['returns'] = df['close'].pct_change()
    df['log_returns'] = np.log(df['close'] / df['close'].shift(1))
    df['std_vol_20'] = df['log_returns'].rolling(20, min_periods=5).std()
    df['range'] = (df['high'] - df['low']) / df['close']

    def window_autocorr(x):
        if len(x) < 3:
            return np.nan
        s = pd.Series(x)
        return s.autocorr(lag=1)
    
    df['autocorr_5'] = df['returns'].rolling(5, min_periods=3).apply(lambda x: window_autocorr(x), raw=True)
    df['momentum'] = df['close'] / df['close'].shift(5) - 1

    return df

def calculate_trend_and_wavelet_features(df_subset):
    df = df_subset.copy()
    df['ma_fast'] = df['close'].rolling(8, min_periods=1).mean()
    df['ma_slow'] = df['close'].rolling(21, min_periods=1).mean()
    df['trend_strength'] = (df['ma_fast'] - df['ma_slow']) / df['ma_slow']
    df['volume_ratio'] = df['volume'] / df['volume'].rolling(20, min_periods=5).mean()
    
    wv, noise = calculate_wavelet_features_series(df['close'], window=WAVELET_WINDOW)
    df['wavelet_vol'] = wv
    df['noise_level'] = noise

    return df


def check_data_leakage(df_train, df_test):
    max_train = df_train.index.max()
    min_test = df_test.index.min()
    if max_train >= min_test:
        logger.error(f"POSIBLE LEAKAGE DETECTADO: train.max={max_train}, test.min={min_test}")
        return False
    logger.info(f"Split temporal OK: train max {max_train} < test min {min_test}")
    return True


def train_hmm_with_wavelets(df_train, features=None):
    logger.info(f"Entrenando HMM con {HMM_N_STATES} estados fijos...")
    if features is None:
        features = ['log_returns', 'wavelet_vol', 'autocorr_5', 'trend_strength', 'range']

    X_train_raw = df_train[features].dropna().values
    if X_train_raw.shape[0] < MIN_TRAIN_ROWS:
        logger.warning("Datos de entrenamiento insuficientes para HMM")
        return None, None, None, None

    scaler = RobustScaler()
    X_train = scaler.fit_transform(X_train_raw)
    X_train = np.nan_to_num(X_train)

    try:
        model = hmm.GaussianHMM(
            n_components=HMM_N_STATES,
            covariance_type="diag",
            n_iter=1000,
            random_state=42,
            tol=0.01
        )
        model.fit(X_train)
        states_train = model.predict(X_train)
        logger.info(f"HMM entrenado con {HMM_N_STATES} estados fijos (train samples: {len(states_train)})")
        return model, states_train, X_train_raw, scaler
    except Exception as e:
        logger.exception(f"Error entrenando HMM: {e}")
        return None, None, None, None

def analyze_wavelet_states_simple(X_original, states):

    logger.info("Analizando 3 estados fijos: Consolidación, Tendencia Alcista, Tendencia Bajista")
    state_info = {}
    unique_states = np.unique(states)
    
    if len(unique_states) == 0:
        logger.warning("No hay estados únicos en la secuencia")
        return state_info
    
    returns = X_original[:, 0]  
    volatilities = X_original[:, 1]  

    ret_threshold = np.percentile(np.abs(returns), 50) * 0.5  
    vol_threshold = np.percentile(volatilities, 40)  
    
    logger.info(f"Umbrales: ret_threshold={ret_threshold:.6f}, vol_threshold={vol_threshold:.6f}")
    
    for state in unique_states:
        mask = (states == state)
        if np.sum(mask) < 10:
            continue
            
        sd = X_original[mask]
        mean_returns = np.mean(sd[:, 0])
        mean_volatility = np.mean(sd[:, 1])
        mean_trend = np.mean(sd[:, 3])

        if abs(mean_returns) < ret_threshold and mean_volatility < vol_threshold:
            label = 'CONSOLIDACION'
        elif mean_returns > 0:
            label = 'TENDENCIA_ALCISTA'
        else:
            label = 'TENDENCIA_BAJISTA'
        
        state_info[state] = {
            'label': label,
            'count': int(np.sum(mask)),
            'mean_return': float(mean_returns),
            'mean_volatility': float(mean_volatility),
            'mean_trend': float(mean_trend)
        }
        logger.info(f"Estado {state}: {label} | muestras: {state_info[state]['count']} "
                   f"| ret:{mean_returns:.6f} vol:{mean_volatility:.6f}")
    
    return state_info


def predict_states_with_viterbi(model, scaler, df, features):
    states_aligned = np.full(len(df), -1, dtype=int)
    if model is None or scaler is None:
        return states_aligned

    X_df = df[features]
    mask = ~X_df.isnull().any(axis=1)
    if mask.sum() == 0:
        return states_aligned

    X_valid = X_df.loc[mask].values
    try:
        X_scaled = scaler.transform(X_valid)
        X_scaled = np.nan_to_num(X_scaled)
        preds = model.predict(X_scaled)
    except Exception as e:
        logger.exception(f"Error prediciendo estados en test: {e}")
        return states_aligned

    valid_positions = np.flatnonzero(mask.values)
    states_aligned[valid_positions] = preds
    return states_aligned


def generate_transition_signals(df_test, state_info, model, scaler, last_signal_time=None):
    logger.info("Buscando transiciones de régimen (test)...")
    signals = []
    features = ['log_returns', 'wavelet_vol', 'autocorr_5', 'trend_strength', 'range']

    states = predict_states_with_viterbi(model, scaler, df_test, features)
    if len(states) == 0:
        logger.warning("No se pudieron predecir estados en test")
        return signals, last_signal_time

    state_labels = [state_info.get(s, {}).get('label', f'UNKNOWN_{s}') if s != -1 else 'UNKNOWN' for s in states]

    for i in range(3, len(df_test)):
        try:
            state_i = states[i]
            if state_i == -1:
                continue

            idx = df_test.index[i]
            if last_signal_time is not None and (idx - last_signal_time) < timedelta(hours=COOLDOWN_HOURS):
                continue

            current_label = state_labels[i]
            prev_labels = [state_labels[j] for j in range(i-3, i) if j >= 0]

            consolidation_count = sum(1 for lab in prev_labels if 'CONSOLIDACION' in lab)
            if consolidation_count < CONSOLIDATION_REQUIRED:
                continue

            if 'CONSOLIDACION' in current_label:
                continue  

            if 'TENDENCIA_ALCISTA' in current_label:
                signal_direction = 1
                strategy = 'BREAKOUT_BULL'
            elif 'TENDENCIA_BAJISTA' in current_label:
                signal_direction = -1
                strategy = 'BREAKOUT_BEAR'
            else:
                continue

            curr = df_test.iloc[i]
            prev = df_test.iloc[i-1]
            prev2 = df_test.iloc[i-2]

            current_vol = float(curr.get('wavelet_vol', 0.0) or 0.0)
            prev_vol = float(prev.get('wavelet_vol', 0.0) or 0.0)
            prev2_vol = float(prev2.get('wavelet_vol', 0.0) or 0.0)
            avg_prev_vol = (prev_vol + prev2_vol) / 2.0 if (prev_vol + prev2_vol) > 0 else prev_vol

            if avg_prev_vol > 0:
                if current_vol <= avg_prev_vol * VOL_INCREASE_MULT:
                    continue

            price_change = float(curr['close'] - prev['close'])
            two_period_change = float(curr['close'] - prev2['close'])

            if signal_direction == 1:
                ok_price = (price_change > MIN_PRICE_MOVE) or (two_period_change > MIN_PRICE_MOVE)
            else:
                ok_price = (price_change < -MIN_PRICE_MOVE) or (two_period_change < -MIN_PRICE_MOVE)

            if not ok_price:
                continue

            signal_info = {
                'timestamp': df_test.index[i].strftime('%Y.%m.%d %H:%M'),
                'valid_for_time': (df_test.index[i] + timedelta(hours=1)).strftime('%Y.%m.%d %H:%M'),
                'price': round(curr['close'], 5),
                'regime': current_label,
                'regime_state': int(state_i),
                'strategy_used': strategy,
                'signal': int(signal_direction),
                'volatility': round(current_vol, 6),
                'noise_level': round(float(curr.get('noise_level', np.nan) or 0.0), 6),
                'trend_deviation': round(float(curr.get('trend_strength', np.nan) or 0.0), 6),
                'prev_regime': prev_labels[-1] if prev_labels else None,
                'index': df_test.index[i]
            }
            signals.append(signal_info)
            last_signal_time = df_test.index[i]
            logger.info(f"Señal {len(signals)} -> {signal_info['timestamp']} | {signal_info['prev_regime']} -> {signal_info['regime']}")
        except Exception:
            logger.exception("Error generando señal en iteración")
            continue

    return signals, last_signal_time


def main():
    start_time = time.time()
    try:
        logger.info("INICIANDO DETECTOR DE TRANSICIONES DE RÉGIMEN (3 estados fijos)")
        connect_mt5(account=account, password=password, server=server)

        df = get_historical_data(SYMBOL, TIMEFRAME, LOOKBACK_WINDOW)
        logger.info(f"Registros crudos: {len(df)}")

        df_basic = calculate_basic_features(df)
        logger.info("Features básicas calculadas.")

        if TRAIN_WINDOW < MIN_TRAIN_ROWS:
            raise ValueError(f"TRAIN_WINDOW debe ser >= MIN_TRAIN_ROWS ({MIN_TRAIN_ROWS})")
        if TRAIN_WINDOW > len(df_basic):
            raise ValueError(f"TRAIN_WINDOW ({TRAIN_WINDOW}) es mayor que el total de velas obtenidas ({len(df_basic)})")
        
        RETRAIN = RETRAIN_EVERY
        if RETRAIN_EVERY <= 0 or RETRAIN_EVERY > TRAIN_WINDOW:
            logger.warning("RETRAIN_EVERY inválido o mayor que TRAIN_WINDOW; ajustando RETRAIN_EVERY = TRAIN_WINDOW")
            RETRAIN = TRAIN_WINDOW

        features = ['log_returns', 'wavelet_vol', 'autocorr_5', 'trend_strength', 'range']
        
        all_signals = []
        last_signal_time = None
        last_df_test = None

        max_train_start = len(df_basic) - TRAIN_WINDOW
        if max_train_start < 0:
            raise ValueError("No hay suficientes velas para el TRAIN_WINDOW especificado")

        logger.info(f"Iniciando walk-forward: TRAIN_WINDOW={TRAIN_WINDOW}, RETRAIN_EVERY={RETRAIN}, total_bars={len(df_basic)}")

        train_start = 0
        while train_start <= max_train_start:
            train_end = train_start + TRAIN_WINDOW - 1
            detect_start = train_end + 1
            detect_end = min(train_end + RETRAIN, len(df_basic) - 1)
            logger.info(f"Iteración walk-forward -> train[{train_start}:{train_end}] detect[{detect_start}:{detect_end}]")

            df_train_basic = df_basic.iloc[train_start:train_end + 1].copy()
            df_test_basic = df_basic.iloc[detect_start:detect_end + 1].copy()
            last_df_test = df_test_basic

            df_train = calculate_trend_and_wavelet_features(df_train_basic)
            df_test = calculate_trend_and_wavelet_features(df_test_basic)
            logger.info("Features calculadas por separado (sin leakage).")

            if not check_data_leakage(df_train, df_test):
                raise RuntimeError("Se detectó posible data leakage entre train y test. Revisa el split y las fechas.")

            model, states_train, X_original, scaler = train_hmm_with_wavelets(df_train, features=features)

            if model is None:
                logger.warning("Fallo entrenamiento, intentando fallback simple (2 estados)")
                features_min = ['log_returns', 'wavelet_vol', 'trend_strength']
                X_train_raw = df_train[features_min].dropna().values
                if X_train_raw.shape[0] >= MIN_TRAIN_ROWS:
                    scaler = RobustScaler()
                    X_train = scaler.fit_transform(X_train_raw)
                    model = hmm.GaussianHMM(n_components=2, covariance_type="diag", n_iter=500, random_state=42)
                    model.fit(X_train)
                    states_train = model.predict(X_train)
                    X_original = X_train_raw
                    logger.info("HMM entrenado con fallback (2 estados)")
                else:
                    logger.error("HMM training failed with all configurations")
                    train_start += RETRAIN
                    continue

            state_info = analyze_wavelet_states_simple(X_original, states_train)
            
            if not state_info:
                logger.warning("No se pudo generar clasificación de estados; aplicando etiquetas simples")
                state_info = {}
                for s in np.unique(states_train):
                    mask = (states_train == s)
                    mean_ret = np.mean(X_original[mask][:, 0])
                    if abs(mean_ret) < 0.0005:
                        label = 'CONSOLIDACION'
                    elif mean_ret > 0:
                        label = 'TENDENCIA_ALCISTA'
                    else:
                        label = 'TENDENCIA_BAJISTA'
                    state_info[s] = {'label': label, 'count': int(np.sum(mask))}
                    logger.info(f"Estado {s}: {label} ({int(np.sum(mask))} muestras)")

            logger.info("Buscando señales en datos de test (bloque actual)...")
            block_signals, last_signal_time = generate_transition_signals(
                df_test, state_info, model, scaler, last_signal_time=last_signal_time
            )

            all_signals.extend(block_signals)
            train_start += RETRAIN

        if all_signals:
            signals_df = pd.DataFrame(all_signals)
            output_columns = [
                'timestamp', 'valid_for_time', 'price', 'regime', 'regime_state',
                'strategy_used', 'signal', 'volatility', 'noise_level', 'trend_deviation'
            ]
            for col in output_columns:
                if col not in signals_df.columns:
                    signals_df[col] = None
            signals_df = signals_df[output_columns]
            signals_df.to_csv(OUTPUT_FILE, index=False)
            logger.info(f"{len(signals_df)} señales generadas. Archivo: {OUTPUT_FILE}")

            buys = int((signals_df['signal'] == 1).sum())
            sells = int((signals_df['signal'] == -1).sum())
            logger.info(f"Señales COMPRA: {buys} | Señales VENTA: {sells}")
            
            if 'regime' in signals_df.columns:
                regime_counts = signals_df['regime'].value_counts()
                logger.info("Señales por régimen:")
                for regime, count in regime_counts.items():
                    logger.info(f"  {regime}: {count}")
            
            logger.info("Últimas 5 señales:")
            for row in all_signals[-5:]:
                logger.info(f"{row['timestamp']} | {row['prev_regime']} -> {row['regime']} | {row['strategy_used']} | sig:{row['signal']}")
        else:
            logger.warning("No se generaron señales.")
            if state_info:
                logger.info(f"Estados detectados (último train):")
                for s, info in state_info.items():
                    logger.info(f"  Estado {s}: {info['label']} ({info['count']} muestras)")

    except Exception as e:
        logger.exception(f"ERROR FATAL: {e}")
    finally:
        try:
            mt5.shutdown()
        except Exception:
            pass
        logger.info(f"Tiempo total ejecución: {time.time() - start_time:.2f} seg")

if __name__ == "__main__":
    main()