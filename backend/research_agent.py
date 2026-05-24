"""
Research Agent - Uses Kimi K from Ollama Cloud to summarize earnings reports and documents

Generates alpha by analyzing:
- Earnings reports
- SEC filings (10-K, 10-Q)
- Analyst reports
- Company press releases
- Industry research
"""

import asyncio
import json
import logging
from datetime import datetime
from typing import Optional, Dict, Any
import aiohttp

logger = logging.getLogger(__name__)

class ResearchAgent:
    """Kimi K-powered research summarization for trading alpha generation"""
    
    def __init__(self, ollama_cloud_url: str = "https://api.ollama.cloud"):
        self.ollama_cloud_url = ollama_cloud_url
        self.model = "kimi-k2.5:cloud"
        self.session: Optional[aiohttp.ClientSession] = None
        
    async def initialize(self):
        """Initialize async HTTP session"""
        if not self.session:
            self.session = aiohttp.ClientSession()
    
    async def close(self):
        """Close async session"""
        if self.session:
            await self.session.close()
    
    async def summarize_earnings_report(self, symbol: str, report_text: str, company_name: str = "") -> Dict[str, Any]:
        """
        Summarize earnings report using Kimi K
        
        Args:
            symbol: Stock symbol
            report_text: Full earnings report text
            company_name: Company name for context
        
        Returns:
            Dict with summary, key insights, risks, opportunities
        """
        prompt = f"""Analyze this {symbol} earnings report and provide:
        
1. **Key Metrics**: EPS, Revenue, Margin trends
2. **Growth Drivers**: What's driving revenue/earnings growth
3. **Headwinds**: Key challenges or risks mentioned
4. **Guidance**: Forward guidance and expectations
5. **Competitive Position**: Market share, competitive advantages
6. **Capital Allocation**: Dividends, buybacks, CapEx
7. **Investment Thesis**: Bull case, bear case, valuation

Report:
{report_text[:10000]}  # Limit to first 10K chars

Format as JSON."""

        try:
            await self.initialize()
            
            # Call Kimi K via Ollama Cloud
            async with self.session.post(
                f"{self.ollama_cloud_url}/api/generate",
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "stream": False,
                    "temperature": 0.7
                },
                timeout=aiohttp.ClientTimeout(total=60)
            ) as resp:
                if resp.status == 200:
                    result = await resp.json()
                    try:
                        summary = json.loads(result.get("response", "{}"))
                    except:
                        summary = {"raw_summary": result.get("response", "")}
                    
                    return {
                        "symbol": symbol,
                        "timestamp": datetime.now().isoformat(),
                        "model": "kimi-k2.5",
                        "summary": summary,
                        "confidence": 0.85
                    }
                else:
                    logger.error(f"Ollama Cloud error: {resp.status}")
                    return {"error": "API failed", "status": resp.status}
        
        except Exception as e:
            logger.error(f"Research agent error: {str(e)}")
            return {"error": str(e)}
    
    async def analyze_sec_filing(self, symbol: str, filing_type: str, filing_text: str) -> Dict[str, Any]:
        """
        Analyze SEC filing (10-K, 10-Q, 8-K, Form 4)
        
        Args:
            symbol: Stock symbol
            filing_type: Type of filing (10-K, 10-Q, 8-K, 4)
            filing_text: Full filing text
        
        Returns:
            Dict with key findings and alpha signals
        """
        prompt = f"""Analyze this {filing_type} filing for {symbol}.
        
Extract:
1. **Material Changes**: What changed materially since last filing
2. **Risk Factors**: New or escalating risks
3. **Financial Health**: Debt levels, liquidity, working capital
4. **Business Trends**: Revenue mix, segment performance
5. **Insider Actions**: Buying/selling by executives (if Form 4)
6. **Guidance Changes**: Any updates to forward guidance
7. **Industry Headwinds**: External challenges mentioned

Filing:
{filing_text[:15000]}

Format as JSON with specific numbers/dates where available."""

        try:
            await self.initialize()
            
            async with self.session.post(
                f"{self.ollama_cloud_url}/api/generate",
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "stream": False,
                    "temperature": 0.7
                },
                timeout=aiohttp.ClientTimeout(total=90)
            ) as resp:
                if resp.status == 200:
                    result = await resp.json()
                    try:
                        analysis = json.loads(result.get("response", "{}"))
                    except:
                        analysis = {"raw_analysis": result.get("response", "")}
                    
                    return {
                        "symbol": symbol,
                        "filing_type": filing_type,
                        "timestamp": datetime.now().isoformat(),
                        "analysis": analysis,
                        "model": "kimi-k2.5"
                    }
                else:
                    return {"error": f"API failed: {resp.status}"}
        
        except Exception as e:
            logger.error(f"SEC filing analysis error: {str(e)}")
            return {"error": str(e)}
    
    async def identify_alpha_signals(self, symbol: str, research_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Identify trading alpha signals from research
        
        Looks for:
        - Earnings surprises
        - Analyst estimate changes
        - Insider buying/selling
        - Competitive disadvantages
        - Upcoming catalysts
        - Valuation disconnects
        """
        prompt = f"""Given this research data for {symbol}, identify alpha signals.
        
Data:
{json.dumps(research_data, indent=2)[:8000]}

Identify:
1. **Surprise Signals**: Anything surprising or unexpected?
2. **Catalyst Events**: What could move the stock?
3. **Valuation Signal**: Is stock cheap or expensive relative to growth?
4. **Risk/Reward**: What's the edge here?
5. **Conviction Level**: How confident are you in the signal?
6. **Time Horizon**: Days, weeks, or months to play out?

Format as JSON with specific actionable signals."""

        try:
            await self.initialize()
            
            async with self.session.post(
                f"{self.ollama_cloud_url}/api/generate",
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "stream": False,
                    "temperature": 0.8
                },
                timeout=aiohttp.ClientTimeout(total=60)
            ) as resp:
                if resp.status == 200:
                    result = await resp.json()
                    try:
                        signals = json.loads(result.get("response", "{}"))
                    except:
                        signals = {"raw_signals": result.get("response", "")}
                    
                    return {
                        "symbol": symbol,
                        "timestamp": datetime.now().isoformat(),
                        "alpha_signals": signals,
                        "model": "kimi-k2.5"
                    }
                else:
                    return {"error": f"API failed: {resp.status}"}
        
        except Exception as e:
            logger.error(f"Alpha signal identification error: {str(e)}")
            return {"error": str(e)}

# Singleton instance
_research_agent: Optional[ResearchAgent] = None

async def get_research_agent() -> ResearchAgent:
    """Get or create research agent instance"""
    global _research_agent
    if not _research_agent:
        _research_agent = ResearchAgent()
        await _research_agent.initialize()
    return _research_agent

async def close_research_agent():
    """Close research agent"""
    global _research_agent
    if _research_agent:
        await _research_agent.close()
        _research_agent = None
