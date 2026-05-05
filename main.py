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
                    print(f"[DEBUG] Prix depuis env: ${entry_price:.4f}")
                
                if entry_price:
                    self.position = {
                        'side': 'long',
                        'entry': entry_price,
                        'amount': sol_balance
                    }
                    print(f"Position: {sol_balance} SOL @ ${entry_price:.4f}")
                else:
                    print("Prix d'achat non trouvé.")
            else:
                print("Pas de position SOL.")
        else:
            print("Solde non récupéré.")

    def get_balance(self):
        try:
            return self.exchange.fetch_balance()
        except Exception as e:
            print(f"Erreur: {e}")
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
            print(f"Erreur trades: {e}")
            return None

    def get_candle_data(self):
        try:
            return self.exchange.fetch_ohlcv(self.symbol, self.timeframe, limit=100)
        except Exception as e:
            print(f"Erreur données: {e}")
            return None

    def calculate_rsi(self, closes, period=14):
        if len(closes) < period + 1:
            return None
        deltas = [closes[i] - closes[i-1] for i in range(1, len(closes))]
        gains = [d if d > 0 else 0 for d in deltas[-period:]]
        losses = [-d if d < 0 else 0 for d in deltas[-period:]]
        avg_gain = sum(gains) / period
        avg_loss = sum(losses) / period
        if avg_loss == 0:
            return 100
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

    def calculate_profit(self, current_price):
        if not self.position:
            return None
        entry_price = self.position['entry']
        return ((current_price - entry_price) / entry_price) * 100

    def buy(self, current_price):
        try:
            if not self.balance:
                return False
            
            usdt_balance = float(self.balance.get('USDT', {}).get('available', 0))
            
            if usdt_balance <= self.reserve:
                print(f"Solde {usdt_balance} < {self.reserve}")
                return False
            
            invest_amount = (usdt_balance - self.reserve) * (ALLOCATION_PERCENT / 100)
            
            if invest_amount < 10:
                print(f"Montant {invest_amount} trop faible")
                return False
            
            quantity = invest_amount / current_price
            price_with_margin = current_price * 1.001
            
            order = {
                'currency_pair': self.symbol.replace('/', '_'),
                'side': 'buy',
                'type': 'limit',
                'price': str(price_with_margin),
                'amount': str(quantity)
            }
            
            print(f"ACHAT: {quantity:.4f} SOL @ ${price_with_margin:.2f}")
            result = spotApi.create_order(**order)
            print(f"Commande: {result.id}")
            
            self.position = {
                'side': 'long',
                'entry': current_price,
                'amount': quantity
            }
            
            print(f"[INFO] Prix: ${current_price:.4f}")
            return True
            
        except Exception as e:
            print(f"Erreur: {e}")
            return False

    def sell(self, current_price):
        try:
            if not self.position:
                return False
            
            amount = self.position['amount']
            entry_price = self.position['entry']
            profit_pct = ((current_price - entry_price) / entry_price) * 100
            profit_value = (current_price - entry_price) * amount
            
            print(f"-> Vente: {profit_pct:.2f}% (+{profit_value:.2f}$)")
            
            if profit_pct < self.min_profit:
                print(f"-> Annulée: {profit_pct:.2f}%")
                return False
            
            order = {
                'currency_pair': self.symbol.replace('/', '_'),
                'side': 'sell',
                'type': 'limit',
                'price': str(current_price),
                'amount': str(amount)
            }
            
            print(f"VENTE: {amount:.4f} SOL @ ${current_price:.2f}")
            result = spotApi.create_order(**order)
            print(f"Commande: {result.id}")
            
            self.position = None
            return True
            
        except Exception as e:
            print(f"Erreur: {e}")
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
        print(f"Bot SOL - 3 minutes")
        print(f"Paire: {self.symbol}")
        print(f"{'='*60}")
        
        while True:
            try:
                ohlcv = self.get_candle_data()
                
                if not ohlcv or len(ohlcv) < 50:
                    print("Données insuffisantes...")
                    time.sleep(60)
                    continue
                
                closes = [c[4] for c in ohlcv]
                current_price = closes[-1]
                rsi = self.calculate_rsi(closes)
                
                self.balance = self.get_balance()
                
                if self.balance:
                    usdt_balance = float(self.balance.get('USDT', {}).get('available', 0))
                    sol_balance = float(self.balance.get('SOL', {}).get('available', 0))
                    
                    print(f"\n{datetime.now().strftime('%H:%M:%S')} | Prix: ${current_price:.2f}")
                    print(f"  USDT: {usdt_balance:.2f} | SOL: {sol_balance:.4f}")
                    
                    if self.position:
                        profit_pct = self.calculate_profit(current_price)
                        
                        if profit_pct is not None:
                            entry_price = self.position['entry']
                            target_price = entry_price * (1 + self.take_profit / 100)
                            min_target = entry_price * (1 + self.min_profit / 100)
                            
                            print(f"  -> Profit: {profit_pct:.2f}% | Cible: {target_price:.2f}$ (min: {min_target:.2f}$)")
                            
                            if self.should_sell(current_price, rsi, None, None):
                                print(f"  -> VENTE!")
                                self.sell(current_price)
                            else:
                                print(f"  -> En attente: {profit_pct:.2f}% < {self.min_profit}%")
                    else:
                        print(f"  -> En attente | RSI: {rsi:.1f}")
                        
                        if self.should_buy(rsi):
                            print(f"  -> ACHAT! RSI: {rsi:.1f}")
                            self.buy(current_price)
                
                if rsi is not None:
                    print(f"  RSI: {rsi:.1f}")
                
                # 3 minutes
                time.sleep(180)
                
            except Exception as e:
                print(f"Erreur: {e}")
                time.sleep(60)

if __name__ == "__main__":
    bot = CryptoTradingBot()
    bot.run()
