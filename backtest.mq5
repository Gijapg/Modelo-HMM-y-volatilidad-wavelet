//+------------------------------------------------------------------+
//|              State Space Signals Backtest EA.mq5                |
//|         Estrategia para backtesting de señales      |
//+------------------------------------------------------------------+
#property copyright "Copyright 2024, MetaQuotes Ltd."
#property link      "https://www.mql5.com"
#property version   "1.00"
#property strict

#include <Trade\Trade.mqh>
#include <Trade\PositionInfo.mqh>
#include <Trade\AccountInfo.mqh>

//+------------------------------------------------------------------+
//| Inputs del EA                                                    |
//+------------------------------------------------------------------+
input string   Inp_SignalsFilename = "WAVELET_HMM_USDJPY.txt";  // Archivo con señales
input bool     Inp_UseRiskManagement = true;    // Usar gestión de riesgo
input double   Inp_RiskPercent = 1.0;           // Porcentaje de riesgo por operación
input int      Inp_MagicNumber = 12345;         // Magic Number
input int      Inp_Slippage = 3;                // Slippage permitido (puntos)
input bool     Inp_EnableDebug = true;          // Mostrar mensajes de debug

// Parámetros de SL/TP basados en ATR
input double   Inp_SL_ATR_Multiplier = 3.0;     // Multiplicador ATR para Stop Loss
input double   Inp_TP_ATR_Multiplier = 9.0;     // Multiplicador ATR para Take Profit


//+------------------------------------------------------------------+
//| Variables globales                                               |
//+------------------------------------------------------------------+
CTrade Trade;
CPositionInfo PositionInfo;
CAccountInfo AccountInfo;
string ProcessedSignals[];  // Almacena IDs de señales procesadas
bool PositionOpen = false;  // Bandera para controlar una operación a la vez
double CurrentSL = 0;       // Stop Loss actual para trailing
double CurrentTP = 0;       // Take Profit actual

//+------------------------------------------------------------------+
//| Expert initialization function                                   |
//+------------------------------------------------------------------+
int OnInit()
{
   Trade.SetExpertMagicNumber(Inp_MagicNumber);
   Trade.SetDeviationInPoints(Inp_Slippage);
   ArrayResize(ProcessedSignals, 0);
   PositionOpen = false;
   
   if(Inp_EnableDebug) 
   {
      Print("EA de Backtesting State Space iniciado.");
      Print("Magic Number: ", Inp_MagicNumber);
      Print("Buscando archivo: ", Inp_SignalsFilename);
      Print("Configuración SL/TP: ATR(", Inp_SL_ATR_Multiplier, "/", Inp_TP_ATR_Multiplier, ")");
      Print("Una operación a la vez: ACTIVADO");
   }
   return(INIT_SUCCEEDED);
}

//+------------------------------------------------------------------+
//| Expert tick function                                             |
//+------------------------------------------------------------------+
void OnTick()
{
   // Solo procesar en apertura de nueva vela para backtesting
   static datetime lastBarTime = 0;
   datetime currentBarTime = iTime(_Symbol, PERIOD_CURRENT, 0);
   
   if(currentBarTime == lastBarTime) 
      return;
   
   lastBarTime = currentBarTime;
   
   if(Inp_EnableDebug) 
      Print("Nueva vela detectada: ", TimeToString(currentBarTime));
   
   // Verificar si hay posición abierta
   CheckExistingPosition();
   
   // Si no hay posición abierta, procesar señales
   if(!PositionOpen)
   {
   ProcessSignalsFile();
   }
   
}

//+------------------------------------------------------------------+
//| Verificar si hay posición abierta                                |
//+------------------------------------------------------------------+
void CheckExistingPosition()
{
   PositionOpen = false;
   
   for(int i = PositionsTotal()-1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket > 0 && PositionSelectByTicket(ticket))
      {
         if(PositionGetInteger(POSITION_MAGIC) == Inp_MagicNumber && 
            PositionGetString(POSITION_SYMBOL) == _Symbol)
         {
            PositionOpen = true;
            CurrentSL = PositionGetDouble(POSITION_SL);
            CurrentTP = PositionGetDouble(POSITION_TP);
            
            
            break;
         }
      }
   }
}

//+------------------------------------------------------------------+
//| Procesar archivo de señales State Space                          |
//+------------------------------------------------------------------+
void ProcessSignalsFile()
{
   ResetLastError();
   int handle = FileOpen(Inp_SignalsFilename, FILE_READ|FILE_TXT|FILE_CSV|FILE_ANSI|FILE_COMMON);
   
   if(handle == INVALID_HANDLE)
   {
      if(Inp_EnableDebug) 
      {
         Print("Error al abrir archivo ", Inp_SignalsFilename, ": ", GetLastError());
         Print("Buscando en: Terminal\\Common\\Files\\");
      }
      return;
   }
   
   // Leer y ignorar encabezado (si existe)
   FileReadString(handle);
   
   int signalsFound = 0;
   int signalsExecuted = 0;
   
   while(!FileIsEnding(handle))
   {
      string line = FileReadString(handle);
      string data[];
      
      // Formato: timestamp,valid_for_time,price,regime,regime_state,strategy_used,signal,volatility,noise_level,trend_deviation
      int dataCount = StringSplit(line, ',', data);
      if(dataCount >= 7) 
      {
         string signalTimeStr = data[0];
         string validForTimeStr = data[1];
         double priceAtSignal = StringToDouble(data[2]);
         string strategyUsed = data[5];
         int signal = (int)StringToInteger(data[6]);
         double volatility = dataCount > 7 ? StringToDouble(data[7]) : 0.0;
         double noiseLevel = dataCount > 8 ? StringToDouble(data[8]) : 0.0;
         double trendDeviation = dataCount > 9 ? StringToDouble(data[9]) : 0.0;
         
         signalsFound++;
         
         // Convertir el tiempo de la señal
         datetime validForTime = StringToTime(validForTimeStr);
         
         // Crear ID único para la señal (timestamp + strategy + signal)
         string signalID = validForTimeStr + "_" + strategyUsed + "_" + IntegerToString(signal);
         
         // Verificar si es tiempo de ejecutar esta señal (coincide con la vela actual)
         if(validForTime == iTime(_Symbol, PERIOD_CURRENT, 0))
         {
            // Solo procesar si la señal es válida, no está duplicada y no hay posición abierta
            if(signal != 0 && !IsSignalProcessed(signalID))//&& !PositionOpen
            {
               if(Inp_EnableDebug)
               {
                  Print("Señal State Space encontrada - Hora: ", validForTimeStr, 
                        " Estrategia: ", strategyUsed, 
                        " Señal: ", signal, 
                        " Volatilidad: ", DoubleToString(volatility, 6),
                        " Ruido: ", DoubleToString(noiseLevel, 3),
                        " Dev.Tendencia: ", DoubleToString(trendDeviation, 1));
               }
               
               ExecuteSignal(signalID, validForTime, signal, priceAtSignal, volatility, noiseLevel, trendDeviation, strategyUsed);
               signalsExecuted++;
               
               // Salir después de ejecutar una señal (una operación a la vez)
               break;
            }
         }
      }
   }
   
   FileClose(handle);
   
   if(Inp_EnableDebug && signalsFound > 0)
      Print("Procesadas ", signalsFound, " señales. Ejecutadas: ", signalsExecuted);
}

//+------------------------------------------------------------------+
//| Verificar si señal ya fue procesada                              |
//+------------------------------------------------------------------+
bool IsSignalProcessed(const string &id)
{
   for(int i = 0; i < ArraySize(ProcessedSignals); i++)
   {
      if(ProcessedSignals[i] == id) 
         return true;
   }
   return false;
}

enum ENUM_ATR_METHOD
  {
   ATR_SMA,    // 0 - Simple Moving Average
   ATR_EMA,    // 1 - Exponential Moving Average  
   ATR_RMA,    // 2 - Wilder's RMA (Relative Moving Average)
   ATR_LWMA,   // 3 - Linear Weighted Moving Average
   ATR_SMMA    // 4 - Smoothed Moving Average
  };

double iATR_Custom(string symbol, ENUM_TIMEFRAMES timeframe, int period, 
                   ENUM_ATR_METHOD method = ATR_RMA, int shift = 0)
  {
//--- Verificar parámetros
   if(period <= 0)
     {
      Print("Error: Period must be greater than 0");
      return 0;
     }

//--- Obtener datos necesarios (period+1 para calcular TR correctamente)
   int barsNeeded = period + shift + 2;
   double high[], low[], close[];
   
   if(CopyHigh(symbol, timeframe, 0, barsNeeded, high) < barsNeeded ||
      CopyLow(symbol, timeframe, 0, barsNeeded, low) < barsNeeded ||
      CopyClose(symbol, timeframe, 0, barsNeeded, close) < barsNeeded)
     {
      Print("Error: Failed to copy price data");
      return 0;
     }

//--- Calcular True Range para todas las barras
   double tr[];
   ArrayResize(tr, barsNeeded);
   
   for(int i = 0; i < barsNeeded; i++)
     {
      if(i == 0)
        {
         // Para la primera barra, TR = High - Low
         tr[i] = high[i] - low[i];
        }
      else
        {
         double hl = high[i] - low[i];
         double hc = MathAbs(high[i] - close[i-1]);
         double lc = MathAbs(low[i] - close[i-1]);
         tr[i] = MathMax(hl, MathMax(hc, lc));
        }
     }

//--- Calcular ATR según el método seleccionado
   double atr = 0;
   
   switch(method)
     {
      //-------------------------------------------------------------
      // SMA: Simple Moving Average
      //-------------------------------------------------------------
      case ATR_SMA:
        {
         double sum = 0;
         for(int i = shift; i < period + shift; i++)
            sum += tr[i];
         atr = sum / period;
        }
      break;

      //-------------------------------------------------------------
      // EMA: Exponential Moving Average
      //-------------------------------------------------------------
      case ATR_EMA:
        {
         double multiplier = 2.0 / (period + 1.0);
         
         // Primera EMA es SMA
         double sum = 0;
         for(int i = shift; i < period + shift; i++)
            sum += tr[i];
         atr = sum / period;
         
         // Calcular EMA para barras restantes
         for(int i = period + shift; i < barsNeeded; i++)
            atr = (tr[i] * multiplier) + (atr * (1 - multiplier));
        }
      break;

      //-------------------------------------------------------------
      // RMA: Wilder's Relative Moving Average
      //-------------------------------------------------------------
      case ATR_RMA:
        {
         // Primera RMA es SMA
         double sum = 0;
         for(int i = shift; i < period + shift; i++)
            sum += tr[i];
         atr = sum / period;
         
         // Fórmula de Wilder: RMA = (PrevRMA * (n-1) + CurrentTR) / n
         for(int i = period + shift; i < barsNeeded; i++)
            atr = (atr * (period - 1) + tr[i]) / period;
        }
      break;

      //-------------------------------------------------------------
      // LWMA: Linear Weighted Moving Average
      //-------------------------------------------------------------
      case ATR_LWMA:
        {
         double sum = 0;
         double weightSum = 0;
         
         // Pesos lineales: más reciente = mayor peso
         for(int i = 0; i < period; i++)
           {
            int weight = period - i; // El más reciente tiene peso máximo
            sum += tr[shift + i] * weight;
            weightSum += weight;
           }
         atr = sum / weightSum;
        }
      break;

      //-------------------------------------------------------------
      // SMMA: Smoothed Moving Average
      //-------------------------------------------------------------
      case ATR_SMMA:
        {
         // Primera SMMA es SMA
         double sum = 0;
         for(int i = shift; i < period + shift; i++)
            sum += tr[i];
         atr = sum / period;
         
         // Fórmula SMMA: SMMA = (PrevSMMA * (n-1) + CurrentTR) / n
         // Nota: Esta es la misma fórmula que RMA pero con interpretación diferente
         for(int i = period + shift; i < barsNeeded; i++)
            atr = (atr * (period - 1) + tr[i]) / period;
        }
      break;

      default:
         Print("Error: Unknown ATR method");
         return 0;
     }

//--- Normalizar y retornar
   int digits = (int)SymbolInfoInteger(symbol, SYMBOL_DIGITS);
   return NormalizeDouble(atr, digits);
  }


//+-------------------------------------------------+
//| Calcular niveles de Stop Loss y Take Profit  |
//+-------------------------------------------------+
void CalculateSLTP(int signal, double entryPrice, double &stopLoss, double &takeProfit)
{
   // Calcular ATR
   double atrBuffer[];
   ArraySetAsSeries(atrBuffer, true);
   double atrValue = iATR_Custom(_Symbol, PERIOD_CURRENT, 14, ATR_RMA, 0);
  
   
   if(signal == 1) // COMPRA
   {
      stopLoss = entryPrice - (atrValue * Inp_SL_ATR_Multiplier);
      takeProfit = entryPrice + (atrValue * Inp_TP_ATR_Multiplier);
   }
   else if(signal == -1) // VENTA
   {
      stopLoss = entryPrice + (atrValue * Inp_SL_ATR_Multiplier);
      takeProfit = entryPrice - (atrValue * Inp_TP_ATR_Multiplier);
   }
   
   // Ajustar a los dígitos del símbolo
   double point = SymbolInfoDouble(_Symbol, SYMBOL_POINT);
   int digits = (int)SymbolInfoInteger(_Symbol, SYMBOL_DIGITS);
   
   stopLoss = NormalizeDouble(stopLoss, digits);
   takeProfit = NormalizeDouble(takeProfit, digits);
   
   if(Inp_EnableDebug)
      Print("SL/TP calculados - Entry: ", entryPrice, " SL: ", stopLoss, " TP: ", takeProfit, " ATR: ", atrValue);
   
}



double CalculateLotSize(double entryPrice, double stopLossPrice, int opType)
{
   // Calcular el valor monetario a riskear (1% del balance)
   double accountBalance = AccountInfoDouble(ACCOUNT_BALANCE);
   double riskAmount = accountBalance * (Inp_RiskPercent / 100.0);
   
   // Calcular la distancia del stop loss en pips
   double slDistancePoints;
   if(opType == ORDER_TYPE_SELL)
      slDistancePoints = MathAbs(entryPrice - stopLossPrice);
   else
      slDistancePoints = MathAbs(stopLossPrice - entryPrice);
   
   // Calcular el valor de un pip para el par
   double tickSize = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
   double tickValue = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE);
   double pointValue = tickValue / (tickSize / SymbolInfoDouble(_Symbol, SYMBOL_POINT));
   
   // Calcular el tamaño de lote requerido
   double moneyAtRiskPerLot = slDistancePoints / SymbolInfoDouble(_Symbol, SYMBOL_POINT) * pointValue;
   
   if(moneyAtRiskPerLot <= 0) return 0.01; // Valor por defecto seguro
   
   double lots = riskAmount / moneyAtRiskPerLot;
   
   // Ajustar a los límites del broker y redondear
   double minLot = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double maxLot = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
   double lotStep = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
   
   lots = MathMax(minLot, MathMin(maxLot, lots));
   lots = MathRound(lots / lotStep) * lotStep;
   
   Print("Balance: ", accountBalance, " RiskAmount: ", riskAmount, " Lots: ", lots);
   return lots;
}

//+------------------------------------------------------------------+
//| Ejecutar señal                                      |
//+------------------------------------------------------------------+
void ExecuteSignal(const string &id, const datetime signalTime, const int signal, 
                   const double price, const double volatility, const double noiseLevel,
                   const double trendDeviation, const string &strategy)
{
   // Agregar ID a señales procesadas
   int newSize = ArraySize(ProcessedSignals) + 1;
   ArrayResize(ProcessedSignals, newSize);
   ProcessedSignals[newSize-1] = id;
   
   // Obtener precios actuales
   double askPrice = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double bidPrice = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double entryPrice = (signal == 1) ? askPrice : bidPrice;
   
   // Calcular Stop Loss y Take Profit
   double stopLoss = 0.0, takeProfit = 0.0;
   CalculateSLTP(signal, entryPrice, stopLoss, takeProfit);
   
   // Calcular tamaño de lote
   double lotSize = CalculateLotSize(entryPrice, stopLoss, signal);
   
   // Cerrar cualquier posición existente antes de abrir nueva
   //CloseAllPositions();
   
   if(signal == 1) // COMPRA
   {
      if(!Trade.Buy(lotSize, _Symbol, 0, stopLoss, takeProfit, strategy))
      {
         if(Inp_EnableDebug) 
            Print("Error en COMPRA: ", GetLastError(), " - ", Trade.ResultRetcodeDescription());
      }
      else
      {
         PositionOpen = true;
         CurrentSL = stopLoss;
         CurrentTP = takeProfit;
         if(Inp_EnableDebug)
         {
            Print("COMPRA ejecutada - Estrategia: ", strategy, 
                  " Precio: ", askPrice, " SL: ", stopLoss, " TP: ", takeProfit,
                  " Lotes: ", lotSize);
         }
      }
   }
   else if(signal == -1) // VENTA
   {
      if(!Trade.Sell(lotSize, _Symbol, 0, stopLoss, takeProfit, strategy))
      {
         if(Inp_EnableDebug) 
            Print("Error en VENTA: ", GetLastError(), " - ", Trade.ResultRetcodeDescription());
      }
      else
      {
         PositionOpen = true;
         CurrentSL = stopLoss;
         CurrentTP = takeProfit;
         if(Inp_EnableDebug)
         {
            Print("VENTA ejecutada - Estrategia: ", strategy, 
                  " Precio: ", bidPrice, " SL: ", stopLoss, " TP: ", takeProfit,
                  " Lotes: ", lotSize);
         }
      }
   }
}

//+------------------------------------------------------------------+
//| Cerrar todas las posiciones                                      |
//+------------------------------------------------------------------+
void CloseAllPositions()
{
   for(int i = PositionsTotal()-1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket > 0 && PositionSelectByTicket(ticket))
      {
         if(PositionGetInteger(POSITION_MAGIC) == Inp_MagicNumber && 
            PositionGetString(POSITION_SYMBOL) == _Symbol)
         {
            Trade.PositionClose(ticket);
            if(Inp_EnableDebug) 
               Print("Posición cerrada: ", ticket);
         }
      }
   }
   PositionOpen = false;
}

//+------------------------------------------------------------------+
//| Expert deinitialization function                                 |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   if(Inp_EnableDebug) 
      Print("EA de Backtesting State Space detenido. Razón: ", reason);
   
   ArrayFree(ProcessedSignals);
}
//+------------------------------------------------------------------+