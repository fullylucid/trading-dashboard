#!/usr/bin/env python3
"""
Insider Trading Detection Script for Tradeskeebot
Scans SEC Form 4 filings for insider purchases/sales with clustering detection
"""

import requests
import json
import time
import sys
import os
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from collections import defaultdict

class InsiderDetector:
    def __init__(self, log_dir="/home/user/.hermes/logs"):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept-Encoding': 'gzip, deflate',
        })
        
        # Symbol to CIK mapping (expanded from OpenClaw)
        self.SYMBOL_TO_CIK = {
            'RKLB': '0001819989',
            'SMCI': '0000712034',
            'CRDO': '0001841101',  # Cerro Dynamics (approx)
            'GLW': '0000024741',   # Corning
            'GFS': '0001617850',   # GFS
            'AMD': '0000002488',
            'PLTR': '0001321655',
            'INTC': '0000050104',
            'USAR': '0001823649',
            'AMSC': '0000044312',
            'XNDU': '0001841092',
            'NBIS': '0001841092',
            'CELH': '0001378590',
            'NVDA': '0001045810',
            'MU': '0000723125',
            'AAPL': '0000320193',
            'MSFT': '0000789019',
            'GOOGL': '0001652044',
            'AMZN': '0001018724',
            'TSLA': '0001318605',
            'META': '0001326801',
        }
        
        self.log_dir = log_dir
        os.makedirs(log_dir, exist_ok=True)
        
        # Rate limiting
        self.last_request_time = 0
        self.min_request_interval = 0.1  # 10 requests per second max
    
    def _rate_limit(self):
        """Enforce rate limiting of 10 requests per second"""
        elapsed = time.time() - self.last_request_time
        if elapsed < self.min_request_interval:
            time.sleep(self.min_request_interval - elapsed)
        self.last_request_time = time.time()
    
    def _get_cik(self, symbol: str) -> Optional[str]:
        """Get CIK for a symbol"""
        return self.SYMBOL_TO_CIK.get(symbol.upper())
    
    def get_recent_form4(self, symbol: str, days_back: int = 7) -> List[Dict]:
        """Get recent Form 4 insider filings for a symbol"""
        cik = self._get_cik(symbol)
        if not cik:
            return []
        
        # Calculate date range
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days_back)
        start_date_str = start_date.strftime('%Y-%m-%d')
        
        url = "https://efts.sec.gov/LATEST/search-index"
        params = {
            'q': f'"{symbol}"',
            'dateRange': 'custom',
            'startdt': start_date_str,
            'forms': '4'
        }
        
        self._rate_limit()
        try:
            response = self.session.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            filings = []
            if 'hits' in data and 'hits' in data['hits']:
                for hit in data['hits']['hits']:
                    source = hit.get('_source', {})
                    display_names = source.get('display_names', [])
                    filer_name = ''
                    if display_names:
                        raw = display_names[0]
                        filer_name = raw.split('(CIK')[0].strip()
                    
                    filing = {
                        'symbol': symbol,
                        'filing_type': 'FORM_4',
                        'filed_date': source.get('file_date', ''),
                        'filer_name': filer_name,
                        'period': source.get('period_ending', ''),
                        'accession_no': source.get('adsh', ''),
                        'form': source.get('form', '4'),
                        'cik': source.get('ciks', [''])[0],
                        'description': source.get('file_description', ''),
                    }
                    filings.append(filing)
            
            return filings
        except Exception as e:
            self._log(f"Error fetching Form 4 for {symbol}: {e}")
            return []
    
    def detect_insider_buying_cluster(self, symbol: str, days_back: int = 30) -> Optional[Dict]:
        """Detect cluster of insider purchases (strong bullish signal)"""
        filings = self.get_recent_form4(symbol, days_back=days_back)
        
        if not filings:
            return None
        
        # Group by transaction type and dates
        purchases = defaultdict(list)
        for filing in filings:
            # Parse transaction type from description
            desc = (filing.get('description') or '').upper()
            if 'SALE' not in desc and 'SOLD' not in desc:  # Exclude sales
                date_str = filing.get('filed_date', '')
                if date_str:
                    purchases[date_str].append(filing)
        
        # Look for clusters (multiple purchases in short window)
        if len(purchases) >= 3:  # 3+ purchase dates in the period
            total_unique_dates = len(purchases)
            unique_filers = set(f.get('filer_name', '') for dates in purchases.values() for f in dates)
            
            return {
                'symbol': symbol,
                'signal_type': 'INSIDER_BUYING_CLUSTER',
                'confidence': min(85, 60 + (total_unique_dates * 5)),  # Higher confidence for more activity
                'purchase_dates': total_unique_dates,
                'unique_buyers': len(unique_filers),
                'days_window': days_back,
                'filings_found': len(filings),
                'last_filing_date': filings[0].get('filed_date', ''),
                'buyers': list(unique_filers)[:5],  # Top 5 buyers
                'reason': f"Insider buying cluster: {len(unique_filers)} executives purchased in {total_unique_dates} separate transactions over {days_back} days"
            }
        
        return None
    
    def detect_major_insider_purchase(self, symbol: str, days_back: int = 7) -> Optional[Dict]:
        """Detect major insider purchase (CEO/Director/Officer buy)"""
        filings = self.get_recent_form4(symbol, days_back=days_back)
        
        recent_buys = []
        for filing in filings:
            desc = (filing.get('description') or '').upper()
            if 'SALE' not in desc and 'SOLD' not in desc:
                # Check for officer/director titles
                filer = filing.get('filer_name', '').upper()
                if any(title in filer or title in desc for title in ['CEO', 'CHIEF EXECUTIVE', 'PRESIDENT', 'CFO', 'COO', 'CHAIRMAN', 'DIRECTOR']):
                    recent_buys.append(filing)
        
        if recent_buys:
            return {
                'symbol': symbol,
                'signal_type': 'MAJOR_INSIDER_BUY',
                'confidence': 80,
                'filings_found': len(recent_buys),
                'executives': [f.get('filer_name', 'Unknown') for f in recent_buys[:3]],
                'last_filing_date': recent_buys[0].get('filed_date', ''),
                'reason': f"CEO/Director purchase detected: {len(recent_buys)} officer buys in past {days_back} days"
            }
        
        return None
    
    def detect_material_events(self, symbol: str, days_back: int = 7) -> List[Dict]:
        """Detect 8-K material events"""
        url = "https://efts.sec.gov/LATEST/search-index"
        cik = self._get_cik(symbol)
        if not cik:
            return []
        
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days_back)
        start_date_str = start_date.strftime('%Y-%m-%d')
        
        params = {
            'q': f'"{symbol}"',
            'dateRange': 'custom',
            'startdt': start_date_str,
            'forms': '8-K'
        }
        
        self._rate_limit()
        try:
            response = self.session.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            events = []
            if 'hits' in data and 'hits' in data['hits']:
                for hit in data['hits']['hits']:
                    source = hit.get('_source', {})
                    desc = source.get('file_description', '').upper()
                    items = source.get('items', '')
                    
                    # Score based on item types
                    score = 50
                    reason = "Material event filed"
                    
                    if any(x in desc for x in ['ACQUISITION', 'MERGER', 'BUSINESS COMBINATION']):
                        score = 90
                        reason = "Acquisition/Merger announced"
                    elif any(x in desc for x in ['CONTRACT', 'AGREEMENT']):
                        if 'GOVERNMENT' in desc:
                            score = 85
                            reason = "Government contract awarded"
                        else:
                            score = 70
                            reason = "Major contract announced"
                    elif 'BANKRUPTCY' in desc or 'DELISTING' in desc:
                        score = 95
                        reason = "Critical material event"
                    elif 'EARNINGS' in desc:
                        score = 60
                        reason = "Earnings announcement"
                    
                    events.append({
                        'symbol': symbol,
                        'signal_type': '8-K_EVENT',
                        'filed_date': source.get('file_date', ''),
                        'confidence': score,
                        'event_items': items,
                        'description': desc[:100],
                        'reason': reason,
                        'accession_no': source.get('adsh', '')
                    })
            
            return events
        except Exception as e:
            self._log(f"Error fetching 8-K events for {symbol}: {e}")
            return []
    
    def _log(self, message: str):
        """Log to insider scan log"""
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        log_file = os.path.join(self.log_dir, 'insider-scan.log')
        with open(log_file, 'a') as f:
            f.write(f"[{timestamp}] {message}\n")
    
    def scan_watchlist(self, symbols: List[str]) -> Dict:
        """Scan entire watchlist for insider signals"""
        all_signals = []
        
        for symbol in symbols:
            self._log(f"Scanning {symbol} for insider activity...")
            
            # Check for buying clusters
            cluster = self.detect_insider_buying_cluster(symbol, days_back=30)
            if cluster:
                all_signals.append(cluster)
                self._log(f"  ✓ Cluster buy detected: {cluster['reason']}")
            
            # Check for major buys
            major_buy = self.detect_major_insider_purchase(symbol, days_back=7)
            if major_buy:
                all_signals.append(major_buy)
                self._log(f"  ✓ Major insider buy: {major_buy['reason']}")
            
            # Check for 8-K events
            events = self.detect_material_events(symbol, days_back=7)
            for event in events:
                if event['confidence'] >= 70:  # Only include significant events
                    all_signals.append(event)
                    self._log(f"  ✓ Material event: {event['reason']}")
        
        # Sort by confidence descending
        all_signals.sort(key=lambda x: x.get('confidence', 0), reverse=True)
        
        return {
            'timestamp': datetime.now().isoformat(),
            'symbols_scanned': len(symbols),
            'signals_found': len(all_signals),
            'high_confidence': len([s for s in all_signals if s.get('confidence', 0) >= 80]),
            'signals': all_signals
        }

def send_telegram_alert(signal: Dict, telegram_token: str, chat_id: str) -> bool:
    """Send alert to Telegram"""
    try:
        import urllib.parse
        import urllib.request
        
        confidence = signal.get('confidence', 0)
        emoji = '🔥' if confidence >= 80 else '⚡'
        
        message = f"""{emoji} INSIDER SIGNAL [{signal['symbol']}]
Type: {signal.get('signal_type', 'UNKNOWN')}
Confidence: {confidence}%
Reason: {signal.get('reason', 'SEC filing detected')}
Date: {signal.get('last_filing_date', signal.get('filed_date', 'N/A'))}"""
        
        url = f"https://api.telegram.org/bot{telegram_token}/sendMessage"
        data = {
            'chat_id': chat_id,
            'text': message,
            'parse_mode': 'HTML'
        }
        
        data_encoded = urllib.parse.urlencode(data).encode('utf-8')
        req = urllib.request.Request(url, data=data_encoded)
        response = urllib.request.urlopen(req, timeout=10)
        return response.getcode() == 200
    except Exception as e:
        print(f"Error sending Telegram alert: {e}")
        return False

if __name__ == "__main__":
    # Default watchlist from Tradeskeebot memory
    watchlist = ['SMCI', 'CRDO', 'GLW', 'GFS', 'AMD', 'PLTR', 'INTC', 'USAR', 'AMSC', 'XNDU', 'NBIS']
    
    detector = InsiderDetector()
    results = detector.scan_watchlist(watchlist)
    
    print(f"\n{'='*70}")
    print(f"INSIDER TRADING SCAN RESULTS")
    print(f"{'='*70}")
    print(f"Symbols scanned: {results['symbols_scanned']}")
    print(f"Total signals found: {results['signals_found']}")
    print(f"High confidence (>80%): {results['high_confidence']}")
    print(f"\n")
    
    # Display signals
    for signal in results['signals'][:10]:  # Show top 10
        print(f"{signal.get('symbol')} | {signal.get('signal_type')} | {signal.get('confidence')}% confidence")
        print(f"  └─ {signal.get('reason', 'N/A')}")
        print()
    
    # Save results
    results_file = "/home/user/.hermes/logs/insider-signals.json"
    with open(results_file, 'w') as f:
        json.dump(results, f, indent=2, default=str)
    
    print(f"Results saved to {results_file}")
