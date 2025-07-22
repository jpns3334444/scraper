"""
Daily digest generation and email notification for Lean v1.3.

This module generates a single daily digest email containing:
- Header with market snapshot
- BUY_CANDIDATE table (limited to 10 best properties)
- WATCH summary statistics
- CSV attachment with full candidate data

Replaces per-property email notifications in Lean v1.3.
"""

import csv
import json
import logging
import os
from datetime import datetime, timezone
from io import StringIO
from typing import Any, Dict, List, Optional

import boto3
from botocore.exceptions import ClientError

from ai_infra.lambda.util.config import get_config
from analysis.lean_scoring import Verdict

logger = logging.getLogger(__name__)


class DailyDigestGenerator:
    """Generate and send daily digest emails."""

    def __init__(self, s3_bucket: Optional[str] = None):
        """
        Initialize the digest generator.
        
        Args:
            s3_bucket: S3 bucket name, defaults to config OUTPUT_BUCKET
        """
        self.config = get_config()
        self.s3_bucket = s3_bucket or self.config.get_str('OUTPUT_BUCKET')
        self.s3_client = boto3.client('s3', region_name=self.config.get_str('AWS_REGION'))
        self.ses_client = boto3.client('ses', region_name=self.config.get_str('AWS_REGION'))
        
    def generate_and_send_digest(self, date_str: Optional[str] = None) -> Dict[str, Any]:
        """
        Generate and send daily digest email.
        
        Args:
            date_str: Date string (YYYY-MM-DD), defaults to today
            
        Returns:
            Dictionary with generation results and metrics
        """
        if not date_str:
            date_str = datetime.now(timezone.utc).strftime('%Y-%m-%d')
            
        logger.info(f"Starting daily digest generation for {date_str}")
        
        results = {
            'date': date_str,
            'digest_generated': False,
            'email_sent': False,
            'metrics': {
                'total_candidates': 0,
                'buy_candidates': 0,
                'watch_candidates': 0,
                'email_recipients': 0,
                'error_count': 0
            }
        }
        
        try:
            # Load candidate data
            candidates = self._load_candidates(date_str)
            results['metrics']['total_candidates'] = len(candidates)
            
            if not candidates:
                logger.info(f"No candidates found for {date_str}")
                return results
                
            # Filter and sort candidates
            buy_candidates, watch_candidates = self._filter_candidates(candidates)
            results['metrics']['buy_candidates'] = len(buy_candidates)
            results['metrics']['watch_candidates'] = len(watch_candidates)
            
            # Load market snapshot
            market_snapshot = self._load_market_snapshot()
            
            # Generate HTML digest
            html_content = self._generate_html_digest(
                buy_candidates, watch_candidates, market_snapshot, date_str
            )
            
            # Generate CSV data
            csv_content = self._generate_csv_digest(candidates)
            
            # Save digest files to S3
            self._save_digest_files(html_content, csv_content, date_str)
            results['digest_generated'] = True
            
            # Send email
            self._send_digest_email(html_content, csv_content, date_str)
            results['email_sent'] = True
            results['metrics']['email_recipients'] = 1  # Single digest email
            
            logger.info(f"Daily digest sent successfully for {date_str}")
            
        except Exception as e:
            logger.error(f"Error generating daily digest: {e}", exc_info=True)
            results['metrics']['error_count'] += 1
            results['error_message'] = str(e)
            
        return results
        
    def _load_candidates(self, date_str: str) -> List[Dict[str, Any]]:
        """Load candidate data from S3."""
        logger.info(f"Loading candidates for {date_str}")
        
        candidates = []
        candidates_prefix = f'candidates/{date_str}/'
        
        try:
            # List all candidate files for the date
            response = self.s3_client.list_objects_v2(
                Bucket=self.s3_bucket,
                Prefix=candidates_prefix
            )
            
            if 'Contents' not in response:
                logger.warning(f"No candidate files found for {date_str}")
                return candidates
                
            # Load each candidate file
            for obj in response['Contents']:
                if obj['Key'].endswith('.json'):
                    try:
                        file_response = self.s3_client.get_object(
                            Bucket=self.s3_bucket,
                            Key=obj['Key']
                        )
                        candidate_data = json.loads(file_response['Body'].read().decode('utf-8'))
                        candidates.append(candidate_data)
                        
                    except Exception as e:
                        logger.error(f"Error loading candidate file {obj['Key']}: {e}", exc_info=True)
                        results['metrics']['error_count'] = results.get('metrics', {}).get('error_count', 0) + 1
                        
            logger.info(f"Loaded {len(candidates)} candidates from {candidates_prefix}")
            
        except Exception as e:
            logger.error(f"Failed to load candidates for {date_str}: {e}", exc_info=True)
            raise e
            
        return candidates
        
    def _filter_candidates(self, candidates: List[Dict[str, Any]]) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """Filter and sort candidates by verdict."""
        buy_candidates = []
        watch_candidates = []
        
        for candidate in candidates:
            # Handle different verdict structures
            verdict = None
            if 'verdict' in candidate:
                verdict = candidate['verdict']
            elif 'components' in candidate and 'verdict' in candidate['components']:
                verdict = candidate['components']['verdict']
            
            # Convert verdict to string if it's an enum
            if hasattr(verdict, 'value'):
                verdict_str = verdict.value
            elif isinstance(verdict, str):
                verdict_str = verdict.upper()
            else:
                verdict_str = str(verdict).upper() if verdict else 'UNKNOWN'
                
            if verdict_str == Verdict.BUY_CANDIDATE.value:
                buy_candidates.append(candidate)
            elif verdict_str == Verdict.WATCH.value:
                watch_candidates.append(candidate)
                
        # Sort by final_score descending, handling different structures
        def get_score(candidate):
            if 'final_score' in candidate:
                return candidate['final_score']
            elif 'components' in candidate and 'final_score' in candidate['components']:
                return candidate['components']['final_score']
            else:
                return 0
                
        buy_candidates.sort(key=get_score, reverse=True)
        watch_candidates.sort(key=get_score, reverse=True)
        
        # Limit buy candidates for email (max 10)
        buy_candidates_for_email = buy_candidates[:10]
        
        logger.info(f"Filtered to {len(buy_candidates_for_email)} BUY candidates, {len(watch_candidates)} WATCH candidates")
        
        return buy_candidates_for_email, watch_candidates
        
    def _load_market_snapshot(self) -> Optional[Dict[str, Any]]:
        """Load global market snapshot."""
        try:
            response = self.s3_client.get_object(
                Bucket=self.s3_bucket,
                Key='snapshots/current/global.json'
            )
            snapshot = json.loads(response['Body'].read().decode('utf-8'))
            logger.debug("Loaded global market snapshot")
            return snapshot
            
        except ClientError as e:
            if e.response['Error']['Code'] == 'NoSuchKey':
                logger.info("No global market snapshot found - will proceed without market data")
            else:
                logger.warning(f"Error loading market snapshot: {e}", exc_info=True)
            return None
        except Exception as e:
            logger.error(f"Unexpected error loading market snapshot: {e}", exc_info=True)
            return None
            
    def _generate_html_digest(self, buy_candidates: List[Dict[str, Any]], 
                            watch_candidates: List[Dict[str, Any]], 
                            market_snapshot: Optional[Dict[str, Any]], 
                            date_str: str) -> str:
        """Generate HTML digest content."""
        logger.info("Generating HTML digest")
        
        # Header section
        header_html = self._generate_header_html(market_snapshot, date_str)
        
        # BUY candidates table
        buy_table_html = self._generate_buy_candidates_table(buy_candidates)
        
        # WATCH summary
        watch_summary_html = self._generate_watch_summary(watch_candidates)
        
        # Combine into full HTML
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <title>Tokyo Real Estate Daily Digest - {date_str}</title>
            <style>
                body {{ font-family: Arial, sans-serif; margin: 40px; }}
                .header {{ background-color: #f8f9fa; padding: 20px; border-radius: 8px; margin-bottom: 30px; }}
                .section {{ margin-bottom: 30px; }}
                .section h2 {{ color: #2c3e50; border-bottom: 2px solid #3498db; padding-bottom: 10px; }}
                table {{ border-collapse: collapse; width: 100%; }}
                th, td {{ border: 1px solid #ddd; padding: 12px; text-align: left; }}
                th {{ background-color: #3498db; color: white; }}
                .buy-candidate {{ background-color: #d4edda; }}
                .watch-candidate {{ background-color: #fff3cd; }}
                .price {{ font-weight: bold; color: #27ae60; }}
                .score {{ font-weight: bold; }}
                .high-score {{ color: #27ae60; }}
                .medium-score {{ color: #f39c12; }}
                .footer {{ margin-top: 40px; padding: 20px; background-color: #ecf0f1; border-radius: 8px; }}
            </style>
        </head>
        <body>
            {header_html}
            {buy_table_html}
            {watch_summary_html}
            <div class="footer">
                <p><strong>Tokyo Real Estate AI Analysis</strong></p>
                <p>Generated on {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}</p>
                <p>Lean v1.3 Pipeline - Deterministic scoring with LLM qualitative analysis</p>
            </div>
        </body>
        </html>
        """
        
        return html_content
        
    def _generate_header_html(self, market_snapshot: Optional[Dict[str, Any]], date_str: str) -> str:
        """Generate header section with market overview."""
        if market_snapshot:
            median_price = market_snapshot.get('median_price_per_sqm', 0)
            total_active = market_snapshot.get('total_active', 0)
            change_pp = market_snapshot.get('seven_day_change_pp', 0)
            
            return f"""
            <div class="header">
                <h1>Tokyo Real Estate Daily Digest - {date_str}</h1>
                <div style="display: flex; justify-content: space-between;">
                    <div>
                        <h3>Market Snapshot</h3>
                        <p><strong>Median Price:</strong> ¥{median_price:,.0f}/sqm</p>
                        <p><strong>Active Listings:</strong> {total_active:,}</p>
                    </div>
                    <div>
                        <h3>7-Day Change</h3>
                        <p style="color: {'green' if change_pp >= 0 else 'red'};">
                            <strong>{change_pp:+.2f} pp</strong>
                        </p>
                    </div>
                </div>
            </div>
            """
        else:
            return f"""
            <div class="header">
                <h1>Tokyo Real Estate Daily Digest - {date_str}</h1>
                <p><em>Market snapshot unavailable</em></p>
            </div>
            """
            
    def _generate_buy_candidates_table(self, buy_candidates: List[Dict[str, Any]]) -> str:
        """Generate BUY candidates table."""
        if not buy_candidates:
            return """
            <div class="section">
                <h2>BUY Candidates</h2>
                <p>No BUY candidates found for today.</p>
            </div>
            """
            
        rows_html = ""
        for candidate in buy_candidates:
            # Extract key fields - handle different data structures
            property_id = candidate.get('property_id') or candidate.get('id', 'N/A')
            price = candidate.get('price', 0)
            size_sqm = candidate.get('total_sqm') or candidate.get('size_sqm', 0)
            price_per_sqm = candidate.get('price_per_sqm', 0)
            ward = candidate.get('ward', 'N/A')
            
            # Handle different score structures
            if 'final_score' in candidate:
                final_score = candidate['final_score']
            elif 'components' in candidate and 'final_score' in candidate['components']:
                final_score = candidate['components']['final_score']
            else:
                final_score = 0
                
            # Handle ward discount from different structures
            if 'ward_discount_pct' in candidate:
                ward_discount_pct = candidate['ward_discount_pct']
            elif 'components' in candidate and 'ward_discount_pct' in candidate['components']:
                ward_discount_pct = candidate['components']['ward_discount_pct']
            else:
                ward_discount_pct = 0
            
            # LLM analysis summary
            llm_analysis = candidate.get('llm_analysis', {})
            if not llm_analysis and 'evaluation' in candidate:
                llm_analysis = candidate['evaluation']
                
            upsides = llm_analysis.get('upsides', [])
            risks = llm_analysis.get('risks', [])
            
            upsides_text = '; '.join(upsides[:2]) if upsides else 'N/A'
            risks_text = '; '.join(risks[:2]) if risks else 'N/A'
            
            score_class = 'high-score' if final_score >= 85 else 'medium-score'
            
            rows_html += f"""
            <tr class="buy-candidate">
                <td>{property_id}</td>
                <td class="price">¥{price:,.0f}</td>
                <td>{size_sqm:.1f}m²</td>
                <td class="price">¥{price_per_sqm:,.0f}/m²</td>
                <td>{ward}</td>
                <td class="score {score_class}">{final_score:.1f}</td>
                <td>{ward_discount_pct:.1f}%</td>
                <td style="max-width: 200px; font-size: 12px;">{upsides_text}</td>
                <td style="max-width: 200px; font-size: 12px;">{risks_text}</td>
            </tr>
            """
            
        return f"""
        <div class="section">
            <h2>BUY Candidates ({len(buy_candidates)} properties)</h2>
            <table>
                <thead>
                    <tr>
                        <th>Property ID</th>
                        <th>Price</th>
                        <th>Size</th>
                        <th>Price/m²</th>
                        <th>Ward</th>
                        <th>Score</th>
                        <th>Discount</th>
                        <th>Key Upsides</th>
                        <th>Key Risks</th>
                    </tr>
                </thead>
                <tbody>
                    {rows_html}
                </tbody>
            </table>
        </div>
        """
        
    def _generate_watch_summary(self, watch_candidates: List[Dict[str, Any]]) -> str:
        """Generate WATCH candidates summary."""
        if not watch_candidates:
            return """
            <div class="section">
                <h2>WATCH Summary</h2>
                <p>No WATCH candidates found for today.</p>
            </div>
            """
            
        # Calculate summary statistics with improved score handling
        def get_score_for_stats(candidate):
            if 'final_score' in candidate:
                return candidate['final_score']
            elif 'components' in candidate and 'final_score' in candidate['components']:
                return candidate['components']['final_score']
            else:
                return 0
                
        avg_score = sum(get_score_for_stats(c) for c in watch_candidates) / len(watch_candidates)
        avg_price_per_sqm = sum(c.get('price_per_sqm', 0) for c in watch_candidates) / len(watch_candidates)
        
        # Count by ward
        ward_counts = {}
        for candidate in watch_candidates:
            ward = candidate.get('ward', 'Unknown')
            ward_counts[ward] = ward_counts.get(ward, 0) + 1
            
        top_wards = sorted(ward_counts.items(), key=lambda x: x[1], reverse=True)[:5]
        wards_text = ', '.join(f"{ward} ({count})" for ward, count in top_wards)
        
        return f"""
        <div class="section">
            <h2>WATCH Summary ({len(watch_candidates)} properties)</h2>
            <div style="display: flex; justify-content: space-between;">
                <div style="flex: 1;">
                    <p><strong>Average Score:</strong> {avg_score:.1f}</p>
                    <p><strong>Average Price/m²:</strong> ¥{avg_price_per_sqm:,.0f}</p>
                </div>
                <div style="flex: 2;">
                    <p><strong>Top Wards:</strong> {wards_text}</p>
                    <p><strong>Note:</strong> WATCH properties scored 60-74 or have ward discounts between -8% and -11.99%</p>
                </div>
            </div>
        </div>
        """
        
    def _generate_csv_digest(self, candidates: List[Dict[str, Any]]) -> str:
        """Generate CSV digest content."""
        logger.info("Generating CSV digest")
        
        output = StringIO()
        
        # Define CSV columns
        fieldnames = [
            'property_id', 'verdict', 'final_score', 'price', 'total_sqm', 'price_per_sqm',
            'ward', 'ward_discount_pct', 'building_age_years',
            'upsides', 'risks', 'justification'
        ]
        
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        
        for candidate in candidates:
            # Extract LLM analysis from different possible structures
            llm_analysis = candidate.get('llm_analysis', {})
            if not llm_analysis and 'evaluation' in candidate:
                llm_analysis = candidate['evaluation']
                
            upsides = '; '.join(llm_analysis.get('upsides', []))
            risks = '; '.join(llm_analysis.get('risks', []))
            justification = llm_analysis.get('justification', '')
            
            # Handle verdict from different structures
            verdict = candidate.get('verdict', '')
            if not verdict and 'components' in candidate:
                verdict = candidate['components'].get('verdict', '')
            if hasattr(verdict, 'value'):
                verdict = verdict.value
                
            # Handle scores from different structures
            final_score = candidate.get('final_score', 0)
            if not final_score and 'components' in candidate:
                final_score = candidate['components'].get('final_score', 0)
                
            ward_discount_pct = candidate.get('ward_discount_pct', 0)
            if not ward_discount_pct and 'components' in candidate:
                ward_discount_pct = candidate['components'].get('ward_discount_pct', 0)
            
            row = {
                'property_id': candidate.get('property_id') or candidate.get('id', ''),
                'verdict': verdict,
                'final_score': final_score,
                'price': candidate.get('price', 0),
                'total_sqm': candidate.get('total_sqm') or candidate.get('size_sqm', 0),
                'price_per_sqm': candidate.get('price_per_sqm', 0),
                'ward': candidate.get('ward', ''),
                'ward_discount_pct': ward_discount_pct,
                'building_age_years': candidate.get('building_age_years', 0),
                'upsides': upsides,
                'risks': risks,
                'justification': justification
            }
            
            writer.writerow(row)
            
        csv_content = output.getvalue()
        output.close()
        
        return csv_content
        
    def _save_digest_files(self, html_content: str, csv_content: str, date_str: str) -> None:
        """Save digest files to S3 with error handling."""
        logger.info("Saving digest files to S3")
        
        try:
            # Save HTML file
            html_key = f'reports/daily/{date_str}/digest.html'
            self.s3_client.put_object(
                Bucket=self.s3_bucket,
                Key=html_key,
                Body=html_content.encode('utf-8'),
                ContentType='text/html',
                Metadata={'generated_at': datetime.now(timezone.utc).isoformat()}
            )
            logger.debug(f"Saved HTML digest: {html_key}")
            
            # Save CSV file
            csv_key = f'reports/daily/{date_str}/digest.csv'
            self.s3_client.put_object(
                Bucket=self.s3_bucket,
                Key=csv_key,
                Body=csv_content.encode('utf-8'),
                ContentType='text/csv',
                Metadata={'generated_at': datetime.now(timezone.utc).isoformat()}
            )
            logger.debug(f"Saved CSV digest: {csv_key}")
            
            logger.info(f"Successfully saved digest files for {date_str}")
            
        except ClientError as e:
            error_code = e.response['Error']['Code']
            logger.error(f"AWS S3 error saving digest files: {error_code} - {e}")
            raise e
        except Exception as e:
            logger.error(f"Unexpected error saving digest files: {e}", exc_info=True)
            raise e
        
    def _send_digest_email(self, html_content: str, csv_content: str, date_str: str) -> None:
        """Send digest email via SES with comprehensive error handling."""
        logger.info("Preparing to send digest email")
        
        from_email = self.config.get_str('EMAIL_FROM', '')
        to_email = self.config.get_str('EMAIL_TO', '')
        
        if not from_email or not to_email:
            logger.error(f"Missing email configuration: FROM='{from_email}', TO='{to_email}'")
            raise ValueError("Email FROM and TO addresses must be configured")
            
        logger.info(f"Sending digest email from {from_email} to {to_email}")
        
        try:
            # Create email with CSV attachment
            import email.mime.multipart
            import email.mime.text
            import email.mime.base
            import email.encoders
            import email.utils
            
            msg = email.mime.multipart.MIMEMultipart()
            msg['Subject'] = f'Tokyo Real Estate Daily Digest - {date_str}'
            msg['From'] = from_email
            msg['To'] = to_email
            msg['Date'] = email.utils.formatdate(localtime=True)
            
            # Attach HTML body
            html_part = email.mime.text.MIMEText(html_content, 'html', 'utf-8')
            msg.attach(html_part)
            
            # Attach CSV only if there's meaningful data
            if csv_content and len(csv_content.strip()) > 50:  # More than just headers
                csv_attachment = email.mime.base.MIMEBase('text', 'csv')
                csv_attachment.set_payload(csv_content.encode('utf-8'))
                email.encoders.encode_base64(csv_attachment)
                csv_attachment.add_header(
                    'Content-Disposition', 
                    f'attachment; filename="tokyo_digest_{date_str}.csv"'
                )
                msg.attach(csv_attachment)
                logger.debug("CSV attachment added to email")
            else:
                logger.info("Skipping CSV attachment - insufficient data")
            
            # Send email
            raw_message = msg.as_string()
            logger.debug(f"Email message size: {len(raw_message)} bytes")
            
            self.ses_client.send_raw_email(
                Source=from_email,
                Destinations=[to_email],
                RawMessage={'Data': raw_message}
            )
            
            logger.info(f"Daily digest email successfully sent to {to_email}")
            
        except ClientError as e:
            error_code = e.response['Error']['Code']
            error_message = e.response['Error']['Message']
            logger.error(f"AWS SES error sending email: {error_code} - {error_message}")
            
            # Provide specific guidance for common SES errors
            if error_code == 'MessageRejected':
                logger.error("Email rejected - check SES sending limits and verification status")
            elif error_code == 'AccessDenied':
                logger.error("SES access denied - check IAM permissions for ses:SendRawEmail")
            elif error_code == 'InvalidParameterValue':
                logger.error("Invalid email parameters - check FROM/TO email addresses")
                
            raise e
            
        except Exception as e:
            logger.error(f"Unexpected error sending digest email: {e}", exc_info=True)
            raise e


def send_daily_digest(event: Dict[str, Any] = None) -> Dict[str, Any]:
    """
    Lambda entry point for daily digest generation and sending.
    
    Args:
        event: Lambda event (optional date parameter)
        
    Returns:
        Results dictionary with metrics
    """
    config = get_config()
    
    # Skip if not in LEAN_MODE
    if not config.is_lean_mode():
        logger.info("Daily digest skipped - LEAN_MODE disabled")
        return {'status': 'skipped', 'reason': 'LEAN_MODE disabled'}
    
    date_str = None
    if event and event.get('date'):
        date_str = event['date']
        
    generator = DailyDigestGenerator()
    results = generator.generate_and_send_digest(date_str)
    
    # Emit metrics
    try:
        from ai_infra.lambda.util.metrics import emit_metric
        emit_metric('Digest.Generated', 1 if results['digest_generated'] else 0)
        emit_metric('Digest.Sent', 1 if results['email_sent'] else 0)
        emit_metric('Digest.BuyCandidates', results['metrics']['buy_candidates'])
        emit_metric('Digest.WatchCandidates', results['metrics']['watch_candidates'])
        emit_metric('Digest.ErrorCount', results['metrics']['error_count'])
    except ImportError:
        logger.warning("Metrics module not available - skipping metric emission")
        
    return results


# Legacy compatibility
class Notifier:
    """Legacy class for backward compatibility."""
    
    def __init__(self):
        self.digest_generator = DailyDigestGenerator()
        
    def send_notification(self, message, channel=None):
        """Legacy method - use DailyDigestGenerator instead."""
        return self.digest_generator.generate_and_send_digest()