"""
CryptoBot - Spot Trading Bot SOL/USDT
Version avec serveur web minimal - CORRIGÉE
CORRECTION: Utilisation de l'historique des ordres au lieu des trades
"""
import os
import sys
import ccxt
import time
import pandas as pd
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler

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


# Classe pour servir une page simple
class SimpleHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()
        response = "<!DOCTYPE html><html><head><title>CryptoBot</title></head><body><h1>Bot SOL/USDT Active</h1><p>===================</p></body></html>"
        self.wfile.write(response.encode())

    def do_HEAD(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()


print("=" * 60)
print("BOT SOL/USDT - VERSION CORRIGEE")
print("=" * 60)
print(f"[DEBUG] API_KEY definie: {bool(API_KEY)}")
print(f"[DEBUG] API_SECRET definie: {bool(API_SECRET)}")
print(f"[DEBUG] PAPER_MODE: {PAPER_MODE}")
print("=" * 60)


class SimpleBot:
    def __init__(self):
        print("[DEBUG] __init__ appele")
        if PAPER_MODE:
            print("Mode : PAPER TRADING")
            self.exchange = ccxt.gateio({'enableRateLimit': True})
            self.balance = {'USDT': 10000, 'SOL': 0}
            self.position = None
        else:
            print("[DEBUG] Mode TRADING REEL - verification des cles")
            if not API_KEY or not API_SECRET:
                print("ERREUR: Les variables d'environnement ne sont pas definies!")
                sys.exit(1)
            print("[DEBUG] Cles API OK - creation de l'echange")
            try:
                self.exchange = ccxt.gateio({
                    'apiKey': API_KEY,
                    'secret': API_SECRET,
                    'enableRateLimit': True,
                    'options': {'createMarketBuyOrderRequiresPrice': False},
                })
                print("[DEBUG] Exchange cree - test de connexion")
                self.exchange.fetch_time()
                print("Connexion a Gate.io reussie!")
            except Exception as e:
                print(f"Erreur de connexion a Gate.io: {e}")
                sys.exit(1)

        print("[DEBUG] Recuperation du solde")
        self.balance = self.get_real_balance()
        print(f"[DEBUG] Solde recupere: USDT={self.balance.get('USDT', 0)}, SOL={self.balance.get('SOL', 0)}")

        sol_balance = float(self.balance.get('SOL', 0))
        if sol_balance >= MIN_POSITION_THRESHOLD:
            # CORRIGE: Essayer d'abord les ordres, puis les trades
            entry_price = self.get_entry_price_from_orders()
            if not entry_price:
                entry_price = self.get_entry_price_from_trades()
            if entry_price:
                self.position = {'side': 'long', 'entry': entry_price, 'amount': sol_balance}
                print(f"Position existante detectee: {sol_balance} SOL @ prix d'achat: ${entry_price:.4f}")
            else:
                # Si on ne peut pas récupérer le prix, demander à l'utilisateur
                print(f"ATTENTION: Impossible de trouver le prix d'achat automatiquement!")
                print(f"Veuille entrer manuellement le prix d'achat (ex: 86.36) ou appuyez sur Entree pour utiliser le prix actuel:")
                try:
                    manual_entry = input("Prix d'achat manuel (ou Entree): ")
                    if manual_entry.strip():
                        manual_price = float(manual_entry)
                        self.position = {'side': 'long', 'entry': manual_price, 'amount': sol_balance}
                        print(f"Position definie manuellement: {sol_balance} SOL @ ${manual_price:.4f}")
                    else:
                        current_price = self.get_price()
                        if current_price:
                            self.position = {'side': 'long', 'entry': current_price, 'amount': sol_balance}
                            print(f"Position definie au prix actuel: {sol_balance} SOL @ ${current_price:.4f}")
                        else:
                            print(f"Impossible de determiner le prix - position ignoree")
                            self.position = None
                except:
                    current_price = self.get_price()
                    if current_price:
                        self.position = {'side': 'long', 'entry': current_price, 'amount': sol_balance}
                        print(f"Position definie au prix actuel: {sol_balance} SOL @ ${current_price:.4f}")
                    else:
                        self.position = None
        else:
            print(f"Dust ignore: {sol_balance} SOL - Pas de position")
            self.position = None

        print("[DEBUG] __init__ termine avec succes")

    def get_entry_price_from_orders(self):
        """Récupère le prix d'achat depuis l'historique des ordres (plus fiable)"""
        try:
            print("[DEBUG] Recherche du prix d'achat dans l'historique des ordres...")
            # Chercher les ordres d'achat remplis
            orders = self.exchange.fetch_closed_orders(SYMBOL, limit=10)
            buy_orders = [o for o in orders if o['side'] == 'buy' and o['status'] == 'closed']
            if buy_orders:
                # Prendre le dernier ordre d'achat
                last_buy = buy_orders[0]
                price = last_buy.get('average') or last_buy.get('price')
                if price:
                    print(f"[DEBUG] Prix d'achat trouve dans les ordres: ${float(price):.4f}")
                    return float(price)
            print("[DEBUG] Aucun ordre d'achat trouve")
            return None
        except Exception as e:
            print(f"[DEBUG] Erreur lors de la recherche dans les ordres: {e}")
            return None

    def get_entry_price_from_trades(self):
        """Récupère le prix d'achat moyen depuis l'historique des trades"""
        try:
            print("[DEBUG] Recherche du prix d'achat dans l'historique des trades...")
            trades = self.exchange.fetch_my_trades(SYMBOL, limit=20)
            if not trades:
                print("[DEBUG] Aucun trade trouve")
                return None
            # Filtrer seulement les achats
            buy_trades = [t for t in trades if t['side'] == 'buy']
            if buy_trades:
                # Prendre les trades les plus récents
                total_cost = 0
                total_amount = 0
                for t in buy_trades[:5]:  # 5 derniers achats
                    total_cost += t.get('cost', 0)
                    total_amount += t.get('amount', 0)
                if total_amount > 0:
                    avg_price = total_cost / total_amount
                    print(f"[DEBUG] Prix d'achat moyen trouve: ${avg_price:.4f}")
                    return avg_price
            print("[DEBUG] Aucun trade d'achat trouve dans l'historique")
            return None
        except Exception as e:
            print(f"[DEBUG] Erreur lors de la recherche du prix d'achat: {e}")
            return None

    def get_real_balance(self):
        try:
            balance = self.exchange.fetch_balance()
            usdt_balance = 0
            sol_balance = 0
            if isinstance(balance, dict):
                total = balance.get('total', {})
                if isinstance(total, dict):
                    usdt_balance = float(total.get('USDT', 0) or 0)
                    sol_balance = float(total.get('SOL', 0) or 0)
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
            print(f"Erreur donnees: {e}")
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

            # NOUVELLE LOGIQUE: SI Profit >= 0.5% → VENDRE (peu importe le RSI)
            if profit_pct >= MIN_PROFIT_THRESHOLD and profit_pct > 0:
                print(f" -> Vente RENTABLE: {profit_pct:.2f}% (+{details.get('profit_usdt', 0):.2f}$)")
                return True

            # En attente si profit pas encore atteint
            if not is_profitable:
                target = details.get('target_price', 0)
                print(f" -> En attente: Profit: {profit_pct:.2f}% | Cible: {target:.2f}$ (min: {MIN_PROFIT_THRESHOLD}%)")
            else:
                print(f" -> En attente: Profit: {profit_pct:.2f}% | Minimum: {MIN_PROFIT_THRESHOLD}% requis")

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
            print(f"[DEBUG] Achat - Solde USDT: {total_usdt}, A utiliser: {usdt_to_use}")

            if usdt_to_use > 5:
                amount_before_fee = usdt_to_use / price
                amount_after_fee = amount_before_fee * (1 - TRADING_FEE)

                if amount_after_fee * price >= 7:
                    amount = round(amount_after_fee, 4)
                    if PAPER_MODE:
                        self.balance['USDT'] -= usdt_to_use
                        self.balance['SOL'] += amount
                        self.position = {'side': 'long', 'entry': price, 'amount': amount}
                        print(f"ACHAT simule: {amount:.4f} SOL a ${price}")
                    else:
                        order = self.exchange.create_order(SYMBOL, 'market', 'buy', usdt_to_use)
                        print(f"ACHAT reel: {amount:.4f} SOL a ${price}")
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
                    print(f" -> Vente ANNULEE: Non rentable")
                    return

                amount = sol_balance
                if amount * price >= 7:
                    if PAPER_MODE:
                        self.balance['SOL'] = 0
                        self.balance['USDT'] += amount * price * (1 - TRADING_FEE)
                        print(f"VENTE simulee: {amount:.4f} SOL a ${price}")
                        self.position = None
                    else:
                        order = self.exchange.create_order(SYMBOL, 'market', 'sell', amount)
                        print(f"VENTE reelle: {amount:.4f} SOL a ${price}")
                        self.position = None
        except Exception as e:
            print(f"Erreur vente: {e}")

    def run(self):
        print(f"\n===== DEMARRAGE DU BOT GATE.IO SOL =====")
        print(f"Paire: {SYMBOL}")
        print(f"Timeframe: {TIMEFRAME}")
        print(f"Allocation: {MAX_USDT_PERCENT}% du solde USDT")
        print(f"Seuil d'achat RSI: < {RSI_BUY_THRESHOLD}")
        print(f"Seuil de profit NET: {MIN_PROFIT_THRESHOLD}% (apres {TOTAL_FEES*100}% frais)")
        print(f"Take-Profit: {TAKE_PROFIT_THRESHOLD}%")
        print(f"Reserve: {MIN_USDT_RESERVE}$")
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
                        print(f" Solde USDT: {float(self.balance.get('USDT', 0)):.2f} | SOL: {float(self.balance.get('SOL', 0)):.4f}")

                        sol_balance = float(self.balance.get('SOL', 0))

                        if self.position is None:
                            if self.should_buy(data):
                                print(" -> Signal ACHAT detecte!")
                                self.buy()
                        else:
                            if sol_balance < MIN_POSITION_THRESHOLD:
                                print(f" -> Dust ignore: {sol_balance:.6f} SOL - Position reinitialisee")
                                self.position = None
                                if self.should_buy(data):
                                    print(" -> Signal ACHAT detecte (apres dust)!")
                                    self.buy()
                            else:
                                if self.should_sell(data):
                                    print(" -> Signal VENTE detecte!")
                                    self.sell()

                        rsi = self.calculate_rsi(data)
                        macd, signal = self.calculate_macd(data)
                        print(f" RSI: {rsi:.1f} | MACD: {macd:.2f} (signal: {signal:.2f})")

                # 3 minutes = 180 secondes
                time.sleep(180)
            except KeyboardInterrupt:
                print("\nBot arrete!")
                break
            except Exception as e:
                print(f"Erreur: {e}")
                time.sleep(60)


def run_web_server():
    port = int(os.environ.get('PORT', 10000))
    server = HTTPServer(('0.0.0.0', port), SimpleHandler)
    print(f"Serveur web demarre sur le port {port}")
    server.serve_forever()


if __name__ == '__main__':
    import threading
    print("[DEBUG] Demarrage du serveur web en arriere-plan")
    web_thread = threading.Thread(target=run_web_server, daemon=True)
    web_thread.start()
    print("[DEBUG] Creation du bot")
    bot = SimpleBot()
    print("[DEBUG] Lancement de la boucle principale")
    bot.run()
