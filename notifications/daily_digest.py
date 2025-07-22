"""
Daily digest generation for Lean v1.3.

This module provides helper functions for generating HTML and CSV reports.
The main implementation is in notifications/notifier.py which handles the complete
workflow including S3 integration and email sending.

Generates HTML and CSV reports with:
- Market summary statistics  
- Top candidates table
- Ward-level analysis
- Minimal email-friendly format
"""

import csv
import json
from datetime import datetime
from typing import Dict, List, Any
from io import StringIO


class DailyDigestGenerator:
    """Generate daily digest reports in HTML and CSV formats."""
    
    def __init__(self):
        self.date = datetime.now().strftime('%Y-%m-%d')
    
    def generate_html_digest(self, candidates: List[Dict[str, Any]], 
                           snapshots: Dict[str, Any]) -> str:
        """
        Generate HTML digest from candidates and market snapshots.
        
        Args:
            candidates: List of candidate properties with scores
            snapshots: Market snapshot data (global/ward stats)
            
        Returns:
            HTML string for email digest
        """
        html = f"""
        <html>
        <head>
            <title>Tokyo Real Estate Daily Digest - {self.date}</title>
            <style>
                body {{ font-family: Arial, sans-serif; margin: 20px; }}
                table {{ border-collapse: collapse; width: 100%; margin: 20px 0; }}
                th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
                th {{ background-color: #f2f2f2; }}
                .summary {{ background-color: #f9f9f9; padding: 15px; margin: 20px 0; }}
                .candidate-row {{ background-color: #e8f5e8; }}
            </style>
        </head>
        <body>
            <h1>Tokyo Real Estate Daily Digest</h1>
            <p>Date: {self.date}</p>
            
            {self._generate_summary_section(candidates, snapshots)}
            {self._generate_candidates_table(candidates)}
            {self._generate_market_section(snapshots)}
        </body>
        </html>
        """
        
        return html.strip()
    
    def generate_csv_digest(self, candidates: List[Dict[str, Any]]) -> str:
        """
        Generate CSV digest with candidate properties.
        
        Args:
            candidates: List of candidate properties
            
        Returns:
            CSV string with candidate data
        """
        if not candidates:
            return "No candidates found for today\n"
        
        output = StringIO()
        
        # Define CSV headers
        headers = [
            'id', 'final_score', 'verdict', 'ward_discount_pct',
            'price', 'size_sqm', 'price_per_sqm', 'ward',
            'building_age_years', 'nearest_station_meters'
        ]
        
        writer = csv.DictWriter(output, fieldnames=headers)
        writer.writeheader()
        
        for candidate in candidates:
            row = {}
            for header in headers:
                if header in candidate:
                    row[header] = candidate[header]
                elif header == 'final_score' and 'components' in candidate:
                    row[header] = candidate['components'].get('final_score', 0)
                elif header == 'verdict' and 'components' in candidate:
                    verdict = candidate['components'].get('verdict')
                    row[header] = verdict.value if hasattr(verdict, 'value') else str(verdict)
                elif header == 'ward_discount_pct' and 'components' in candidate:
                    row[header] = candidate['components'].get('ward_discount_pct', 0)
                else:
                    row[header] = ''
            
            writer.writerow(row)
        
        return output.getvalue()
    
    def _generate_summary_section(self, candidates: List[Dict[str, Any]], 
                                 snapshots: Dict[str, Any]) -> str:
        """Generate summary statistics section."""
        total_candidates = len(candidates)
        
        # Count by verdict
        verdict_counts = {}
        for candidate in candidates:
            verdict = candidate.get('components', {}).get('verdict', 'UNKNOWN')
            # Handle different verdict structures
            if hasattr(verdict, 'value'):
                verdict_key = verdict.value
            elif isinstance(verdict, str):
                verdict_key = verdict.upper()
            else:
                verdict_key = str(verdict)
            verdict_counts[verdict_key] = verdict_counts.get(verdict_key, 0) + 1
        
        # Global market stats
        global_stats = snapshots.get('global', {})
        median_price = global_stats.get('median_price_per_sqm', 0)
        total_inventory = global_stats.get('total_properties', 0)
        
        return f"""
        <div class="summary">
            <h2>Market Summary</h2>
            <p><strong>Candidates Found:</strong> {total_candidates}</p>
            <p><strong>Market Median Price/sqm:</strong> ¥{median_price:,.0f}</p>
            <p><strong>Total Market Inventory:</strong> {total_inventory:,} properties</p>
            
            <h3>Candidate Breakdown:</h3>
            <ul>
                {self._format_verdict_counts(verdict_counts)}
            </ul>
        </div>
        """
    
    def _format_verdict_counts(self, verdict_counts: Dict[str, int]) -> str:
        """Format verdict counts as HTML list items."""
        items = []
        for verdict, count in verdict_counts.items():
            items.append(f"<li>{verdict}: {count}</li>")
        return '\n'.join(items)
    
    def _generate_candidates_table(self, candidates: List[Dict[str, Any]]) -> str:
        """Generate candidates table HTML."""
        if not candidates:
            return "<p>No candidates found today.</p>"
        
        # Sort by score descending
        sorted_candidates = sorted(
            candidates, 
            key=lambda x: x.get('components', {}).get('final_score', 0),
            reverse=True
        )
        
        table_html = """
        <h2>Top Candidates</h2>
        <table>
            <tr>
                <th>ID</th>
                <th>Score</th>
                <th>Verdict</th>
                <th>Ward Discount</th>
                <th>Price</th>
                <th>Size</th>
                <th>Price/sqm</th>
                <th>Ward</th>
                <th>Age</th>
                <th>Station</th>
            </tr>
        """
        
        for candidate in sorted_candidates[:10]:  # Top 10 only
            components = candidate.get('components', {})
            verdict = components.get('verdict', 'UNKNOWN')
            verdict_str = verdict.value if hasattr(verdict, 'value') else str(verdict)
            
            table_html += f"""
            <tr class="candidate-row">
                <td>{candidate.get('id', 'N/A')}</td>
                <td>{components.get('final_score', 0):.1f}</td>
                <td>{verdict_str}</td>
                <td>{components.get('ward_discount_pct', 0):.1f}%</td>
                <td>¥{candidate.get('price', 0):,.0f}</td>
                <td>{candidate.get('size_sqm', 0):.1f}m²</td>
                <td>¥{candidate.get('price_per_sqm', 0):,.0f}</td>
                <td>{candidate.get('ward', 'N/A')}</td>
                <td>{candidate.get('building_age_years', 0)}y</td>
                <td>{candidate.get('nearest_station_meters', 0)}m</td>
            </tr>
            """
        
        table_html += "</table>"
        return table_html
    
    def _generate_market_section(self, snapshots: Dict[str, Any]) -> str:
        """Generate market analysis section."""
        ward_stats = snapshots.get('wards', {})
        
        if not ward_stats:
            return "<h2>Market Analysis</h2><p>No ward data available.</p>"
        
        # Get top performing wards
        ward_list = []
        for ward_name, stats in ward_stats.items():
            ward_list.append({
                'name': ward_name,
                'median_price': stats.get('median_price_per_sqm', 0),
                'inventory': stats.get('total_properties', 0),
                'candidates': stats.get('candidate_count', 0)
            })
        
        # Sort by candidate count descending
        ward_list.sort(key=lambda x: x['candidates'], reverse=True)
        
        table_html = """
        <h2>Ward Analysis</h2>
        <table>
            <tr>
                <th>Ward</th>
                <th>Median Price/sqm</th>
                <th>Total Inventory</th>
                <th>Candidates</th>
            </tr>
        """
        
        for ward in ward_list[:8]:  # Top 8 wards
            table_html += f"""
            <tr>
                <td>{ward['name']}</td>
                <td>¥{ward['median_price']:,.0f}</td>
                <td>{ward['inventory']:,}</td>
                <td>{ward['candidates']}</td>
            </tr>
            """
        
        table_html += "</table>"
        return table_html
    
    def generate_digest_package(self, candidates: List[Dict[str, Any]], 
                               snapshots: Dict[str, Any]) -> Dict[str, str]:
        """
        Generate complete digest package (HTML + CSV).
        
        Args:
            candidates: List of candidate properties
            snapshots: Market snapshot data
            
        Returns:
            Dictionary with 'html' and 'csv' keys
        """
        return {
            'html': self.generate_html_digest(candidates, snapshots),
            'csv': self.generate_csv_digest(candidates),
            'date': self.date,
            'candidate_count': len(candidates)
        }


# Convenience functions for backward compatibility
def generate_daily_digest(candidates: List[Dict[str, Any]], 
                         snapshots: Dict[str, Any]) -> Dict[str, str]:
    """
    Convenience function to generate daily digest.
    
    Note: For full functionality including S3 integration and email sending,
    use notifications.notifier.DailyDigestGenerator instead.
    
    Args:
        candidates: List of candidate properties with scoring components
        snapshots: Market snapshot data with global/ward statistics
        
    Returns:
        Dictionary containing HTML and CSV digest content
    """
    generator = DailyDigestGenerator()
    return generator.generate_digest_package(candidates, snapshots)


def send_daily_digest_email(date_str: str = None) -> Dict[str, Any]:
    """
    Main entry point for sending daily digest email.
    
    This function delegates to the main implementation in notifications.notifier.
    
    Args:
        date_str: Date string (YYYY-MM-DD), defaults to today
        
    Returns:
        Dictionary with generation results and metrics
    """
    from notifications.notifier import send_daily_digest
    
    event = {'date': date_str} if date_str else {}
    return send_daily_digest(event)