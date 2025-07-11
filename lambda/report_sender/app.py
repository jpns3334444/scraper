"""
Report Sender Lambda function for generating and delivering Markdown reports.
Processes LLM results and sends via SES email.
"""
import json
import logging
import os
from datetime import datetime
from typing import Any, Dict, List
from urllib.parse import urlparse

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

s3_client = boto3.client('s3')
ses_client = boto3.client('ses')
ssm_client = boto3.client('ssm')


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Main Lambda handler for report generation and delivery.
    
    Args:
        event: Lambda event containing batch results from previous step
        context: Lambda context
        
    Returns:
        Dict containing report delivery status
    """
    try:
        date_str = event.get('date')
        bucket = event.get('bucket', os.environ['OUTPUT_BUCKET'])
        result_key = event.get('result_key')
        batch_result = event.get('batch_result', {})
        
        logger.info(f"Generating report for date: {date_str}")
        
        # Load full batch results if not provided
        if not batch_result:
            batch_result = load_batch_results(bucket, result_key)
        
        # Check if there are any picks
        top_picks = batch_result.get('top_picks', [])
        if not top_picks:
            logger.info("No top picks found, skipping report generation")
            return {
                'statusCode': 200,
                'message': 'No top picks found, report skipped',
                'date': date_str
            }
        
        # Generate Markdown report
        markdown_report = generate_markdown_report(batch_result, date_str)
        
        # Save report to S3
        report_key = f"reports/{date_str}/report.md"
        save_report_to_s3(markdown_report, batch_result, bucket, report_key, date_str)
        
        # Send via email
        email_success = send_via_email(markdown_report, date_str)
        
        logger.info(f"Successfully generated and sent report")
        
        return {
            'statusCode': 200,
            'date': date_str,
            'bucket': bucket,
            'report_key': report_key,
            'top_picks_count': len(top_picks),
            'email_sent': email_success
        }
        
    except Exception as e:
        logger.error(f"Report generation failed: {e}")
        raise


def load_batch_results(bucket: str, key: str) -> Dict[str, Any]:
    """
    Load batch results from S3.
    
    Args:
        bucket: S3 bucket name
        key: S3 key for results file
        
    Returns:
        Batch result dictionary
    """
    try:
        response = s3_client.get_object(Bucket=bucket, Key=key)
        content = response['Body'].read().decode('utf-8')
        full_result = json.loads(content)
        return full_result.get('parsed_result', {})
        
    except Exception as e:
        logger.error(f"Failed to load batch results from s3://{bucket}/{key}: {e}")
        raise


def generate_markdown_report(batch_result: Dict[str, Any], date_str: str) -> str:
    """
    Generate Markdown report from batch results.
    
    Args:
        batch_result: Parsed batch result dictionary
        date_str: Processing date string
        
    Returns:
        Markdown report string
    """
    top_picks = batch_result.get('top_picks', [])
    runners_up = batch_result.get('runners_up', [])
    market_notes = batch_result.get('market_notes', '')
    
    # Generate report header
    report_lines = [
        f"# Tokyo Real Estate Analysis - {date_str}",
        "",
        f"**Analysis Date**: {date_str}",
        f"**Top Picks**: {len(top_picks)}",
        f"**Runners Up**: {len(runners_up)}",
        "",
    ]
    
    # Add market notes if available
    if market_notes:
        report_lines.extend([
            "## Market Overview",
            "",
            market_notes,
            "",
        ])
    
    # Add top picks section
    if top_picks:
        report_lines.extend([
            "## 🏆 Top 5 Picks",
            "",
            "| Rank | ID | Score | Price (¥) | Area (m²) | Price/m² | Age | Walk (min) | Ward |",
            "|------|----|----|----------|-----------|----------|-----|------------|------|"
        ])
        
        for i, pick in enumerate(top_picks, 1):
            price_yen = format_currency(pick.get('price_yen', 0))
            area_m2 = pick.get('area_m2', 0)
            price_per_m2 = format_currency(pick.get('price_per_m2', 0))
            age_years = pick.get('age_years', 'N/A')
            walk_mins = pick.get('walk_mins_station', 'N/A')
            ward = pick.get('ward', 'N/A')
            
            report_lines.append(
                f"| {i} | {pick.get('id', 'N/A')} | {pick.get('score', 'N/A')} | "
                f"{price_yen} | {area_m2} | {price_per_m2} | {age_years} | {walk_mins} | {ward} |"
            )
        
        report_lines.extend(["", "### Detailed Analysis", ""])
        
        for i, pick in enumerate(top_picks, 1):
            report_lines.extend([
                f"#### {i}. Property {pick.get('id', 'N/A')} (Score: {pick.get('score', 'N/A')})",
                "",
                f"**Why**: {pick.get('why', 'No reasoning provided')}",
                ""
            ])
            
            red_flags = pick.get('red_flags', [])
            if red_flags:
                report_lines.extend([
                    "**🚩 Red Flags**:",
                    ""
                ])
                for flag in red_flags:
                    report_lines.append(f"- {flag}")
                report_lines.append("")
    
    # Add runners up section
    if runners_up:
        report_lines.extend([
            "## 🥈 Runners Up",
            "",
            "| ID | Score | Price (¥) | Area (m²) | Price/m² | Ward |",
            "|----|----|----------|-----------|----------|------|"
        ])
        
        for runner in runners_up:
            price_yen = format_currency(runner.get('price_yen', 0))
            area_m2 = runner.get('area_m2', 0)
            price_per_m2 = format_currency(runner.get('price_per_m2', 0))
            ward = runner.get('ward', 'N/A')
            
            report_lines.append(
                f"| {runner.get('id', 'N/A')} | {runner.get('score', 'N/A')} | "
                f"{price_yen} | {area_m2} | {price_per_m2} | {ward} |"
            )
        
        report_lines.append("")
    
    # Add footer
    report_lines.extend([
        "---",
        "",
        "🤖 *Generated by AI Real Estate Analysis System*",
        f"*Report generated on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} JST*"
    ])
    
    return "\n".join(report_lines)


def format_currency(amount: float) -> str:
    """Format currency amount with commas."""
    try:
        return f"¥{int(amount):,}"
    except (ValueError, TypeError):
        return "¥0"


def save_report_to_s3(markdown_report: str, batch_result: Dict[str, Any], bucket: str, report_key: str, date_str: str) -> None:
    """
    Save report and results to S3.
    
    Args:
        markdown_report: Markdown report content
        batch_result: Full batch result dictionary
        bucket: S3 bucket name
        report_key: S3 key for Markdown report
        date_str: Processing date string
    """
    try:
        # Save Markdown report
        s3_client.put_object(
            Bucket=bucket,
            Key=report_key,
            Body=markdown_report.encode('utf-8'),
            ContentType='text/markdown'
        )
        
        # Save JSON results
        json_key = f"reports/{date_str}/results.json"
        s3_client.put_object(
            Bucket=bucket,
            Key=json_key,
            Body=json.dumps(batch_result, ensure_ascii=False, indent=2).encode('utf-8'),
            ContentType='application/json'
        )
        
        logger.info(f"Saved report to s3://{bucket}/{report_key}")
        logger.info(f"Saved results to s3://{bucket}/{json_key}")
        
    except Exception as e:
        logger.error(f"Failed to save report to S3: {e}")
        raise



def send_via_email(markdown_report: str, date_str: str) -> bool:
    """
    Send report via SES email.
    
    Args:
        markdown_report: Markdown report content
        date_str: Processing date string
        
    Returns:
        True if successful, False otherwise
    """
    try:
        email_from = os.environ.get('EMAIL_FROM')
        email_to = os.environ.get('EMAIL_TO')
        
        if not email_from or not email_to:
            logger.warning("Email addresses not configured")
            return False
        
        # Convert Markdown to plain text for email
        plain_text = markdown_to_plain_text(markdown_report)
        
        subject = f"Tokyo Real Estate Analysis - {date_str}"
        
        response = ses_client.send_email(
            Source=email_from,
            Destination={'ToAddresses': [email_to]},
            Message={
                'Subject': {'Data': subject},
                'Body': {
                    'Text': {'Data': plain_text},
                    'Html': {'Data': markdown_to_html(markdown_report)}
                }
            }
        )
        
        logger.info(f"Successfully sent email: {response['MessageId']}")
        return True
        
    except Exception as e:
        logger.error(f"Failed to send email: {e}")
        return False


def markdown_to_plain_text(markdown: str) -> str:
    """Convert Markdown to plain text."""
    import re
    
    # Remove Markdown formatting
    text = re.sub(r'#+\s+', '', markdown)  # Headers
    text = re.sub(r'\*\*(.*?)\*\*', r'\1', text)  # Bold
    text = re.sub(r'\*(.*?)\*', r'\1', text)  # Italic
    text = re.sub(r'\[(.*?)\]\(.*?\)', r'\1', text)  # Links
    text = re.sub(r'`(.*?)`', r'\1', text)  # Inline code
    text = re.sub(r'^\|.*\|$', '', text, flags=re.MULTILINE)  # Table rows
    text = re.sub(r'^\|.*\|$', '', text, flags=re.MULTILINE)  # Table headers
    
    return text


def markdown_to_html(markdown: str) -> str:
    """Convert Markdown to basic HTML."""
    import re
    
    html = markdown
    
    # Headers
    html = re.sub(r'^# (.*)', r'<h1>\1</h1>', html, flags=re.MULTILINE)
    html = re.sub(r'^## (.*)', r'<h2>\1</h2>', html, flags=re.MULTILINE)
    html = re.sub(r'^### (.*)', r'<h3>\1</h3>', html, flags=re.MULTILINE)
    html = re.sub(r'^#### (.*)', r'<h4>\1</h4>', html, flags=re.MULTILINE)
    
    # Bold and italic
    html = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', html)
    html = re.sub(r'\*(.*?)\*', r'<em>\1</em>', html)
    
    # Convert newlines to <br>
    html = html.replace('\n', '<br>\n')
    
    return f"<html><body>{html}</body></html>"


if __name__ == "__main__":
    # For local testing
    test_event = {
        'date': '2025-07-07',
        'bucket': 're-stock',
        'result_key': 'batch_output/2025-07-07/response.json',
        'batch_result': {
            'top_picks': [
                {
                    'id': 'test123',
                    'score': 85,
                    'why': 'Great value property',
                    'red_flags': ['Minor water damage visible'],
                    'price_yen': 25000000,
                    'area_m2': 65.5,
                    'price_per_m2': 381679,
                    'age_years': 15,
                    'walk_mins_station': 8,
                    'ward': 'Shibuya'
                }
            ],
            'runners_up': [],
            'market_notes': 'Strong market conditions in central Tokyo'
        }
    }
    result = lambda_handler(test_event, None)
    print(json.dumps(result, indent=2))