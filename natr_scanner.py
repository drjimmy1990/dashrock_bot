
from binance.um_futures import UMFutures
import pandas_ta as ta
import pandas as pd
import threading
import numpy as np
import requests




def fetch_data(client, symbol, timeframe, limit ):
    

    ohlcv = client.klines(symbol=symbol, interval=timeframe, limit=limit)
    ohlcv_df = pd.DataFrame(ohlcv ,  columns=['timestamp', 'Open', 'High', 'Low', 'Close', 'Volume', 'close_time', 'quote_asset_volume', 'number_of_trades', 'taker_buy_base_asset_volume', 'taker_buy_quote_asset_volume', 'ignore'])
    ohlcv_df = ohlcv_df.drop(['close_time', 'quote_asset_volume', 'number_of_trades', 'taker_buy_base_asset_volume', 'taker_buy_quote_asset_volume', 'ignore'], axis=1)
    ohlcv_df['timestamp'] = pd.to_datetime(ohlcv_df['timestamp'], unit='ms')
    ohlcv_df = ohlcv_df.set_index('timestamp')
    ohlcv_df = ohlcv_df.astype(float)
    natr = 100 * ta.atr(ohlcv_df['High'], ohlcv_df['Low'], ohlcv_df['Close'], length=8) / ohlcv_df['Close']

    ohlcv_df["natr"] = natr
    natr_r = round(ohlcv_df["natr"].iloc[-2] , 1)
    
  

    return (symbol, natr_r)


def run_script(timeframe ):
    client = UMFutures()
    client.session.mount('https://', requests.adapters.HTTPAdapter(pool_maxsize = 1500))
    symbol_list =['BTCUSDT', 'ETHUSDT', 'BCHUSDT', 'XRPUSDT', 'EOSUSDT', 'LTCUSDT', 'TRXUSDT', 'ETCUSDT', 'LINKUSDT', 'XLMUSDT', 'ADAUSDT', 'XMRUSDT', 'DASHUSDT', 'ZECUSDT', 'XTZUSDT', 'BNBUSDT', 'ATOMUSDT', 'ONTUSDT', 'IOTAUSDT', 'BATUSDT', 'VETUSDT', 'NEOUSDT', 'QTUMUSDT', 'IOSTUSDT', 'THETAUSDT', 'ALGOUSDT', 'ZILUSDT', 'KNCUSDT','ZRXUSDT', 'COMPUSDT', 'OMGUSDT', 'DOGEUSDT', 'SXPUSDT', 'KAVAUSDT', 'BANDUSDT', 'RLCUSDT', 'WAVESUSDT', 'MKRUSDT', 'SNXUSDT', 'DOTUSDT', 'DEFIUSDT', 'YFIUSDT', 'BALUSDT', 'CRVUSDT', 'TRBUSDT', 'RUNEUSDT', 'SUSHIUSDT', 'EGLDUSDT', 'SOLUSDT', 'ICXUSDT', 'STORJUSDT', 'BLZUSDT', 'UNIUSDT', 'AVAXUSDT', 'FTMUSDT', 'ENJUSDT', 'FLMUSDT', 'TOMOUSDT', 'RENUSDT', 'KSMUSDT', 'NEARUSDT', 'AAVEUSDT', 'FILUSDT', 'RSRUSDT', 'LRCUSDT', 'MATICUSDT', 'OCEANUSDT', 'BELUSDT', 'CTKUSDT', 'AXSUSDT', 'ALPHAUSDT', 'ZENUSDT', 'SKLUSDT', 'GRTUSDT', '1INCHUSDT', 'CHZUSDT', 'SANDUSDT', 'ANKRUSDT', 'LITUSDT', 'UNFIUSDT', 'REEFUSDT', 'RVNUSDT', 'SFPUSDT', 'XEMUSDT', 'COTIUSDT', 'CHRUSDT', 'MANAUSDT', 'ALICEUSDT', 'HBARUSDT', 'ONEUSDT', 'LINAUSDT', 'STMXUSDT', 'DENTUSDT', 'CELRUSDT', 'HOTUSDT', 'MTLUSDT', 'OGNUSDT', 'NKNUSDT', 'DGBUSDT', '1000SHIBUSDT', 'BAKEUSDT', 'GTCUSDT', 'BTCDOMUSDT', 'IOTXUSDT', 'AUDIOUSDT', 'C98USDT', 'MASKUSDT', 'ATAUSDT', 'DYDXUSDT', '1000XECUSDT', 'GALAUSDT', 'CELOUSDT', 'ARUSDT', 'KLAYUSDT', 'ARPAUSDT', 'CTSIUSDT', 'LPTUSDT', 'ENSUSDT', 'PEOPLEUSDT', 'ANTUSDT', 'ROSEUSDT', 'DUSKUSDT', 'FLOWUSDT', 'IMXUSDT', 'API3USDT', 'GMTUSDT', 'APEUSDT', 'WOOUSDT', 'JASMYUSDT', 'DARUSDT', 'GALUSDT', 'OPUSDT', 'INJUSDT', 'STGUSDT', 'FOOTBALLUSDT', 'SPELLUSDT', '1000LUNCUSDT', 'LUNA2USDT', 'LDOUSDT', 'CVXUSDT', 'ICPUSDT', 'APTUSDT', 'QNTUSDT', 'BLUEBIRDUSDT', 'FETUSDT', 'FXSUSDT', 'HOOKUSDT', 'MAGICUSDT', 'TUSDT', 'RNDRUSDT', 'HIGHUSDT', 'MINAUSDT', 'ASTRUSDT', 'AGIXUSDT', 'PHBUSDT', 'GMXUSDT', 'CFXUSDT', 'STXUSDT', 'COCOSUSDT', 'BNXUSDT', 'ACHUSDT', 'SSVUSDT', 'CKBUSDT', 'PERPUSDT', 'TRUUSDT', 'LQTYUSDT', 'USDCUSDT', 'IDUSDT', 'ARBUSDT', 'ETHUSDT_230630', 'BTCUSDT_230630', 'JOEUSDT', 'TLMUSDT', 'AMBUSDT', 'LEVERUSDT', 'RDNTUSDT', 'HFTUSDT', 'XVSUSDT']
    
    limit = 50
    
    

    threads = []
    results = []

    for symbol in symbol_list:
        thread = threading.Thread(target=lambda r, c=client, s=symbol, t=timeframe, l=limit : r.append(fetch_data(c, s, t, l)), args=(results,))
        thread.start()
        threads.append(thread)

    for thread in threads:
        thread.join()


    
    # create DataFrame
    df = pd.DataFrame({'Symbol': [r[0] for r in results],
                       'natr': [r[1] for r in results]})
    
    
    #convert numeric columns to float
    df['natr'] = df['natr'].astype(float)
    

    #print(datetime.now())
    sorted_df_natr = df.sort_values(by='natr', ascending=False)
    sorted_df_natr = sorted_df_natr.set_index('Symbol')
    print(sorted_df_natr.to_string(index=True))
    print("\n\n")


    






run_script("1m" )
