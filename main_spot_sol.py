"""
CryptoBot - Spot Trading Bot SOL/USDT
Version simplifiée - sans serveur web
"""

import os
import sys
import ccxt
import time
import pandas as pd
from datetime import datetime

# Configuration
SYMBOL = 'SOL/USDT'
TIMEFRAME = '15m'
PAPER_MODE = False

# Clés API Gate.io
API_KEY = os.getenv('GATEIO_API_KEY', '')
API_SECRET = os.getenv('GATEIO_API_SECRET', '')

# Frais Gate.io
TRADING_FEE = 0.001
TOTAL_FEES = 0.002

# Solde minimum à garder en USDT
MIN_USDT_RESERVE = 5

# Pourcentage du solde à utiliser
MAX_USDT_PERCENT = 20

# Seuil de profit minimum NET
MIN_PROFIT_THRESHOLD = 0.5

# Take-Profit automatique
TAKE_PROFIT_THRESHOLD = 2.0

# Seuil RSI pour achat
RSI_BUY_THRESHOLD = 30

# Seuil RSI pour vente
RSI_SELL_THRESHOLD = 70

# Seuil minimum pour une vraie position
MIN_POSITION_THRESHOLD = 0.01

print("=" * 60)
print("BOT SOL/USDT - VERSION SIMPLIFIÉE")
print("=" * 60)
print(f"[DEBUG] API_KEY définie: {bool(API_KEY)}")
print(f"[DEBUG] API_SECRET définie: {bool(API_SECRET)}")
print(f"[DEBUG] PAPER_MODE: {PAPER_MODE}")
print("=" * 60)

class SimpleBot:
    def __init__(self):
        print("[DEBUG] __init__ appelé")
        if PAPER_MODE:
            print("Mode : PAPER TRADING")
            self.exchange = ccxt.gateio({'enableRateLimit': True})
            self.balance = {'USDT': 10000, 'SOL': 0}
            self.position = None
        else:
            print("[DEBUG] Mode TRADING RÉEL - vérification des clés")
            if not API_KEY or not API_SECRET:
                print("ERREUR: Les variables d'environnement ne sont pas définies!")
                sys.exit(1)
            
            print("[DEBUG] Clés API OK - création de l'échange")
            try:
                self.exchange = ccxt.gateio({
                    'apiKey': API_KEY,
                    'secret': API_SECRET,
                    'enableRateLimit': True,
                })
                print("[DEBUG] Exchange créé - test de connexion")
                self.exchange.fetch_time()
                print("Connexion à Gate.io réussie!")
            except Exception as e:
                print(f"Erreur de connexion à Gate.io: {e}")
                sys.exit(1)
            
            print("[DEBUG] Récupération du solde")
            self.balance = self.get_real_balance()
            print(f"[DEBUG] Solde récupéré: USDT={self.balance.get('USDT', 0)}, SOL={self.balance.get('SOL', 0)}")
            
            sol_balance = float(self.balance.get('SOL', 0))
            if sol_balance >= MIN_POSITION_THRESHOLD:
                self.position = {'side': 'long', 'entry': 0, 'amount': sol_balance}
                print(f"Position existante détectée: {sol_balance} SOL")
            else:
                print(f"Dust ignoré: {sol_balance} SOL - Pas de position")
                self.position = None
        print("[DEBUG] __init__ terminé avec succès")

    def get_real_balance(self):
        try:
            print("[DEBUG] fetch_balance appelé")
            balance = self.exchange.fetch_balance()
            usdt_balance = 0
            sol_balance = 0
            if isinstance(balance, dict):
                total = balance.get('total', {})
                if isinstance(total, dict):
                    usdt_balance = float(total.get('USDT', 0) or 0)
                    sol_balance = float(total.get('SOL', 0) or 0)
            print(f"[DEBUG] Balance - USDT: {usdt_balance}, SOL: {sol_balance}")
            return {'USDT': usdt_balance, 'SOL': sol_balance}
        except Exception as e:
            print(f"Erreur solde: {e}")
            return {'USDT': 0, 'SOL': 0}

    def get_price(self):
        try:
            ticker = self.exchange.fetch_ticker(SYMBOL)
            last = ticker.get('last')
            if last is None:
                last = ticker.get('close')
            return float(last) if last is not None else None
        except Exception as e:
            print(f"Erreur prix: {e}")
            return None

    def get_data(self, limit=100):
        try:
            ohlcv = self.exchange.fetch_ohlcv(SYMBOL, TIMEFRAME, limit=limit)
            if not ohlcv or len(ohlcv) < 26:
                return None
            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            df['close'] = pd.to_numeric(df['close'], errors='coerce')
            return df.dropna()
        except Exception as e:
            print(f"Erreur données: {e}")
            return None

    def calculate_rsi(self, data, period=14):
        try:
            if data is None or len(data) < period:
                return 50.0
            closes = data['close'].values
            if len(closes) < period:
                return 50.0
            deltas = []
            for i in range(1, len(closes)):
                deltas.append(float(closes[i]) - float(closes[i-1]))
            gains = [max(d, 0) for d in deltas[-period:]]
            losses = [abs(min(d, 0)) for d in deltas[-period:]]
            avg_gain = sum(gains) / period
            avg_loss = sum(losses) / period
            if avg_loss == 0:
                return 100.0
            rs = avg_gain / avg_loss
            rsi = 100 - (100 / (1 + rs))
            return float(rsi)
        except Exception as e:
            return 50.0

    def calculate_macd(self, data):
        try:
            if data is None or len(data) < 26:
                return 0.0, 0.0
            closes = data['close'].values
            if len(closes) < 26:
                return 0.0, 0.0
            ema12 = self._calculate_ema(closes, 12)
            ema26 = self._calculate_ema(closes, 26)
            macd = ema12 - ema26
            signal = self._calculate_ema([macd] * 9, 9)
            return float(macd), float(signal)
        except Exception as e:
            return 0.0, 0.0

    def _calculate_ema(self, values, period):
        try:
            values = [float(v) for v in values[-period:]]
            multiplier = 2 / (period + 1)
            ema = sum(values) / period
            for value in values[1:]:
                ema = (value * multiplier) + (ema * (1 - multiplier))
            return ema
        except:
            return values[-1] if len(values) > 0 else 0

    def calculate_profitability(self, current_price):
        try:
            if not self.position:
                return True, 0.0, {}
            entry_price = float(self.position.get('entry', 0))
            amount_sol = float(self.position.get('amount', 0))
            if entry_price == 0 or amount_sol == 0:
                return True, 0.0, {}
            break_even_price = entry_price * (1 + TOTAL_FEES)
            target_price = break_even_price * (1 + MIN_PROFIT_THRESHOLD / 100)
            profit_pct = ((current_price - entry_price) / entry_price) * 100
            profit_usdt = (current_price - entry_price) * amount_sol
            is_profitable = current_price > target_price
            take_profit_price = break_even_price * (1 + TAKE_PROFIT_THRESHOLD / 100)
            return is_profitable, float(profit_pct), {
                'entry_price': entry_price,
                'current_price': current_price,
                'break_even_price': break_even_price,
                'target_price': target_price,
                'take_profit_price': take_profit_price,
                'profit_usdt': profit_usdt
            }
        except Exception as e:
            print(f"Erreur calcul profit: {e}")
            return True, 0.0, {}

    def should_buy(self, data):
        try:
            rsi = self.calculate_rsi(data)
            macd, signal = self.calculate_macd(data)
            if rsi < RSI_BUY_THRESHOLD:
                return True
            if macd > signal and rsi < 50:
                return True
            return False
        except Exception as e:
            return False

    def should_sell(self, data):
        try:
            rsi = self.calculate_rsi(data)
            macd, signal = self.calculate_macd(data)
            current_price = self.get_price()
            if current_price is None:
                return False
            is_profitable, profit_pct, details = self.calculate_profitability(current_price)
            if profit_pct >= TAKE_PROFIT_THRESHOLD and profit_pct > 0:
                print(f"  -> TAKE-PROFIT! Vente automatique à {profit_pct:.2f}% (+{details.get('profit_usdt', 0):.2f}$)")
                return True
            if is_profitable and profit_pct >= MIN_PROFIT_THRESHOLD:
                if rsi >= RSI_SELL_THRESHOLD:
                    print(f"  -> Vente RENTABLE (RSI): {profit_pct:.2f}% (+{details.get('profit_usdt', 0):.2f}$)")
                    return True
                if macd < signal and rsi > 50:
                    print(f"  -> Vente RENTABLE (MACD): {profit_pct:.2f}% (+{details.get('profit_usdt', 0):.2f}$)")
                    return True
            if not is_profitable:
                target = details.get('target_price', 0)
                print(f"  -> En attente: Profit: {profit_pct:.2f}% | Cible: {target:.2f}$ (min: {MIN_PROFIT_THRESHOLD}%)")
            else:
                print(f"  -> En attente: Profit: {profit_pct:.2f}% | Minimum: {MIN_PROFIT_THRESHOLD}% requis | RSI: {rsi:.1f}")
            return False
        except Exception as e:
            print(f"Erreur should_sell: {e}")
            return False

    def buy(self):
        try:
            if not PAPER_MODE:
                self.balance = self.get_real_balance()
            price = self.get_price()
            if price is None:
                return
            total_usdt = float(self.balance.get('USDT', 0))
            usdt_to_use = (total_usdt - MIN_USDT_RESERVE) * (MAX_USDT_PERCENT / 100)
            print(f"[DEBUG] Achat - Solde USDT: {total_usdt}, À utiliser: {usdt_to_use}")
            if usdt_to_use > 5:
                amount_before_fee = usdt_to_use / price
                amount_after_fee = amount_before_fee * (1 - TRADING_FEE)
                if amount_after_fee * price >= 7:
                    amount = round(amount_after_fee, 4)
                    if PAPER_MODE:
                        self.balance['USDT'] -= usdt_to_use
                        self.balance['SOL'] += amount
                        self.position = {'side': 'long', 'entry': price, 'amount': amount}
                        print(f"ACHAT simulé: {amount:.4f} SOL à ${price}")
                    else:
                        order = self.exchange.create_order(SYMBOL, 'market', 'buy', usdt_to_use)
                        print(f"ACHAT réel: {amount:.4f} SOL à ${price}")
                        self.position = {'side': 'long', 'entry': price, 'amount': amount}
        except Exception as e:
            print(f"Erreur achat: {e}")

    def sell(self):
        try:
            if not PAPER_MODE:
                self.balance = self.get_real_balance()
            sol_balance = float(self.balance.get('SOL', 0))
            if sol_balance >= MIN_POSITION_THRESHOLD:
                price = self.get_price()
                if price is None:
                    return
                is_profitable, profit_pct, details = self.calculate_profitability(price)
                if not is_profitable:
                    print(f"  -> Vente ANNULÉE: Non rentable")
                    return
                amount = sol_balance
                if amount * price >= 7:
                    if PAPER_MODE:
                        self.balance['SOL'] = 0
                        self.balance['USDT'] += amount * price * (1 - TRADING_FEE)
                        print(f"VENTE simulée: {amount:.4f} SOL à ${price}")
                        self.position = None
                    else:
                        order = self.exchange.create_order(SYMBOL, 'market', 'sell', amount)
                        print(f"VENTE réelle: {amount:.4f} SOL à ${price}")
                        self.position = None
        except Exception as e:
            print(f"Erreur vente: {e}")

    def run(self):
        print(f"\n===== DÉMARRAGE DU BOT GATE.IO SOL =====")
        print(f"Paire: {SYMBOL}")
        print(f"Timeframe: {TIMEFRAME}")
        print(f"Allocation: {MAX_USDT_PERCENT}% du solde USDT")
        print(f"Seuil d'achat RSI: < {RSI_BUY_THRESHOLD}")
        print(f"Seuil de profit NET: {MIN_PROFIT_THRESHOLD}% (après {TOTAL_FEES*100}% frais)")
        print(f"Take-Profit: {TAKE_PROFIT_THRESHOLD}%")
        print(f"Réserve: {MIN_USDT_RESERVE}$")
        print(f"========================================\n")

        while True:
            try:
                if not PAPER_MODE:
                    self.balance = self.get_real_balance()
                data = self.get_data()
                if data is not None:
                    price = self.get_price()
                    if price is not None:
                        print(f"\n{datetime.now().strftime('%H:%M:%S')} | Prix: ${price:,.2f}")
                        print(f"  Solde USDT: {float(self.balance.get('USDT', 0)):.2f} | SOL: {float(self.balance.get('SOL', 0)):.4f}")
                        sol_balance = float(self.balance.get('SOL', 0))
                        if self.position is None:
                            if self.should_buy(data):
                                print("  -> Signal ACHAT détecté!")
                                self.buy()
                        else:
                            if sol_balance < MIN_POSITION_THRESHOLD:
                                print(f"  -> Dust ignoré: {sol_balance:.6f} SOL - Position réinitialisée")
                                self.position = None
                                if self.should_buy(data):
                                    print("  -> Signal ACHAT détecté (après dust)!")
                                    self.buy()
                            else:
                                if self.should_sell(data):
                                    print("  -> Signal VENTE détecté!")
                                    self.sell()
                        rsi = self.calculate_rsi(data)
                        macd, signal = self.calculate_macd(data)
                        print(f"  RSI: {rsi:.1f} | MACD: {macd:.2f} (signal: {signal:.2f})")
                time.sleep(900)
            except KeyboardInterrupt:
                print("\nBot arrêté!")
                break
            except Exception as e:
                print(f"Erreur: {e}")
                time.sleep(60)

if __name__ == '__main__':
    print("[DEBUG] Création du bot")
    bot = SimpleBot()
    print("[DEBUG] Lancement de la boucle principale")
    bot.run()