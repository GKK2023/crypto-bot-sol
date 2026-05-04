import os
import time
import logging
from datetime import datetime
from gate_api import ApiClient, Configuration
from gate_api.api import spot_api
import ccxt

# =============================================================================
# CONFIGURATION
# =============================================================================

API_KEY = os.getenv('GATEIO_API_KEY')
API_SECRET = os.getenv('GATEIO_API_SECRET')
SOL_ENTRY_PRICE = os.getenv('SOL_ENTRY_PRICE')

SYMBOL = 'SOL/USDT'
TIMEFRAME = '15m'
ALLOCATION_PERCENT = 20
MIN_RSI_BUY = 30
MIN_PROFIT_THRESHOLD = 0.5
TAKE_PROFIT_TARGET = 2.0
RESERVE_AMOUNT = 5
MIN_POSITION_THRESHOLD = 0.001

config = Configuration(key=API_KEY, secret=API_SECRET)
api_client = ApiClient(config)
spotApi = spot_api.SpotApi(api_client)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# =============================================================================
# CLASSE DU BOT
# =============================================================================

class CryptoTradingBot:
    def __init__(self):
        self.exchange = ccxt.gateio({
            'apiKey': API_KEY,
            'secret': API_SECRET,
        })
        
        self.symbol = SYMBOL
        self.timeframe = TIMEFRAME
        self.min_rsi_buy = MIN_RSI_BUY
        self.min_profit = MIN_PROFIT_THRESHOLD
        self.take_profit = TAKE_PROFIT_TARGET
        self.reserve = RESERVE_AMOUNT
        self.position = None
        
        self.balance = self.get_balance()
        
        if self.balance:
            usdt_balance = float(self.balance.get('USDT', {}).get('available', 0))
            sol_balance = float(self.balance.get('SOL', {}).get('available', 0))
            
            print(f"[DEBUG] Solde récupéré: USDT={usdt_balance}, SOL={sol_balance}")
            
            if sol_balance >= MIN_POSITION_THRESHOLD:
                entry_price = self.get_entry_price_from_trades(sol_balance)
                
                if not entry_price and SOL_ENTRY_PRICE:
                    entry_price = float(SOL_ENTRY_PRICE)
                    print(f"[DEBUG] Utilisation du prix d'achat depuis env var: ${entry_price:.4f}")
                
                if entry_price:
                    self.position = {
                        'side': 'long',
                        'entry': entry_price,
                        'amount': sol_balance
                    }
                    print(f"Position existante détectée: {sol_balance} SOL au prix d'entrée: ${entry_price:.4f}")
                else:
                    print("Impossible de déterminer le prix d'achat pour la position existante.")
                    self.position = None
            else:
                print("Aucun SOL en position, démarrage normal.")
        else:
            print("Impossible de récupérer le solde.")

    def get_balance(self):
        try:
            return self.exchange.fetch_balance()
        except Exception as e:
            print(f"Erreur lors de la récupération du solde: {e}")
            return None

    def get_entry_price_from_trades(self, amount):
        try:
            trades = self.exchange.fetch_my_trades(symbol=self.symbol, limit=10)
            total_bought = 0
            for trade in trades:
                if trade['side'] == 'buy' and trade['symbol'] == self.symbol:
                    total_bought += trade['amount']
                    if total_bought >= amount * 0.95:
                        return trade['price']
            return None
        except Exception as e:
            print(f"Erreur lors de la récupération des trades: {e}")
            return None

    def get_candle_data(self):
        try:
            ohlcv = self.exchange.fetch_ohlcv(self.symbol, self.timeframe, limit=100)
            return ohlcv
        except Exception as e:
            print(f"Erreur lors de la récupération des données: {e}")
            return None

    def calculate_rsi(self, closes, period=14):
        if len(closes) < period + 1:
            return None
        deltas = []
        for i in range(1, len(closes)):
            deltas.append(closes[i] - closes[i - 1])
        gains = [d if d > 0 else 0 for d in deltas[-period:]]
        losses = [-d if d < 0 else 0 for d in deltas[-period:]]
        avg_gain = sum(gains) / period
        avg_loss = sum(losses) / period
        if avg_loss == 0:
            return 100
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        return rsi

    def calculate_macd(self, closes, fast=12, slow=26, signal=9):
        if len(closes) < slow + signal:
            return None, None
        ema_fast = sum(closes[-fast:]) / fast
        ema_slow = sum(closes[-slow:]) / slow
        macd_line = ema_fast - ema_slow
        signal_line = sum(closes[-signal:]) / signal
        return macd_line, signal_line

    def calculate_profit(self, current_price):
        if not self.position:
            return None
        entry_price = self.position['entry']
        profit_pct = ((current_price - entry_price) / entry_price) * 100
        return profit_pct

    def buy(self, current_price):
        try:
            if not self.balance:
                print("Solde insuffisant pour l'achat.")
                return False
            
            usdt_balance = float(self.balance.get('USDT', {}).get('available', 0))
            
            if usdt_balance <= self.reserve:
                print(f"Solde USDT ({usdt_balance}) inférieur à la réserve ({self.reserve}), achat ignoré.")
                return False
            
            invest_amount = (usdt_balance - self.reserve) * (ALLOCATION_PERCENT / 100)
            
            if invest_amount < 10:
                print(f"Montant à investir ({invest_amount}) trop faible, achat ignoré.")
                return False
            
            quantity = invest_amount / current_price
            price_with_margin = current_price * 1.001
            
            order_params = {
                'currency_pair': self.symbol.replace('/', '_'),
                'side': 'buy',
                'type': 'limit',
                'price': str(price_with_margin),
                'amount': str(quantity)
            }
            
            print(f"ACHAT: {quantity:.4f} SOL @ ${price_with_margin:.2f}")
            result = spotApi.create_order(**order_params)
            
            print(f"Commande d'achat créée: {result.id}")
            
            self.position = {
                'side': 'long',
                'entry': current_price,
                'amount': quantity
            }
            
            print(f"[INFO] Prix d'achat: ${current_price:.4f}")
            
            return True
            
        except Exception as e:
            print(f"Erreur lors de l'achat: {e}")
            return False

    def sell(self, current_price):
        try:
            if not self.position:
                return False
            
            amount = self.position['amount']
            entry_price = self.position['entry']
            
            profit_pct = ((current_price - entry_price) / entry_price) * 100
            profit_value = (current_price - entry_price) * amount
            
            print(f"-> Vente RENTABLE: {profit_pct:.2f}% (+{profit_value:.2f}$)")
            
            if profit_pct < self.min_profit:
                print(f"-> Vente ANNULÉE: Profit trop faible ({profit_pct:.2f}%)")
                return False
            
            order_params = {
                'currency_pair': self.symbol.replace('/', '_'),
                'side': 'sell',
                'type': 'limit',
                'price': str(current_price),
                'amount': str(amount)
            }
            
            print(f"VENTE réelle: {amount:.4f} {self.symbol.split('/')[0]} à ${current_price:.2f}")
            result = spotApi.create_order(**order_params)
            
            print(f"Commande de vente créée: {result.id}")
            
            self.position = None
            
            return True
            
        except Exception as e:
            print(f"Erreur lors de la vente: {e}")
            return False

    def should_buy(self, rsi):
        return rsi is not None and rsi < self.min_rsi_buy

    def should_sell(self, current_price, rsi, macd, signal):
        if not self.position:
            return False
        profit_pct = self.calculate_profit(current_price)
        if profit_pct is None:
            return False
        return profit_pct >= self.min_profit

    def run(self):
        print(f"{'='*60}")
        print(f"Bot SOL démarré")
        print(f"Paire: {self.symbol}")
        print(f"Timeframe: {self.timeframe}")
        print(f"Allocation: {ALLOCATION_PERCENT}% du solde USDT")
        print(f"Seuil d'achat RSI: < {self.min_rsi_buy}")
        print(f"Seuil de profit NET: {self.min_profit}% (après frais)")
        print(f"Take-Profit: {self.take_profit}%")
        print(f"Réserve: {self.reserve}$")
        print(f"{'='*60}")
        
        while True:
            try:
                ohlcv = self.get_candle_data()
                
                if not ohlcv or len(ohlcv) < 50:
                    print("Données insuffisantes, attente...")
                    time.sleep(60)
                    continue
                
                closes = [c[4] for c in ohlcv]
                current_price = closes[-1]
                
                rsi = self.calculate_rsi(closes)
                macd, signal = self.calculate_macd(closes)
                
                self.balance = self.get_balance()
                
                if self.balance:
                    usdt_balance = float(self.balance.get('USDT', {}).get('available', 0))
                    sol_balance = float(self.balance.get('SOL', {}).get('available', 0))
                    
                    print(f"\n{datetime.now().strftime('%H:%M:%S')} | Prix: ${current_price:.2f}")
                    print(f"  Solde USDT: {usdt_balance:.2f} | SOL: {sol_balance:.4f}")
                    
                    if self.position:
                        profit_pct = self.calculate_profit(current_price)
                        
                        if profit_pct is not None:
                            entry_price = self.position['entry']
                            target_price = entry_price * (1 + self.take_profit / 100)
                            min_target = entry_price * (1 + self.min_profit / 100)
                            
                            print(f"  -> En attente: Profit: {profit_pct:.2f}% | Cible: {target_price:.2f}$ (min: {min_target:.2f}$)")
                            
                            if self.should_sell(current_price, rsi, macd, signal):
                                print(f"  -> Signal VENTE détecté!")
                                self.sell(current_price)
                            else:
                                if profit_pct >= self.min_profit:
                                    print(f"  -> En attente: Profit {profit_pct:.2f}% < Seuil {self.min_profit}%")
                                else:
                                    print(f"  -> En attente: Profit {profit_pct:.2f}% insuffisant")
                        else:
                            print(f"  -> En attente: Impossible de calculer le profit")
                    else:
                        print(f"  -> En attente | RSI: {rsi:.1f}")
                        
                        if self.should_buy(rsi):
                            print(f"  -> Signal ACHAT détecté! RSI: {rsi:.1f}")
                            self.buy(current_price)
                
                if rsi is not None:
                    print(f"  RSI: {rsi:.1f}", end="")
                if macd is not None and signal is not None:
                    print(f" | MACD: {macd:.2f} (signal: {signal:.2f})", end="")
                print()
                
                time.sleep(180)
                
            except Exception as e:
                print(f"Erreur dans la boucle principale: {e}")
                time.sleep(60)

# =============================================================================
# EXÉCUTION
# =============================================================================

if __name__ == "__main__":
    bot = CryptoTradingBot()
    bot.run()
