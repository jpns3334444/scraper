"""
Report Sender Lambda function for generating and delivering HTML reports.
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
        
        # Extract HTML report directly from OpenAI response
        html_report = extract_openai_report(batch_result)
        
        # Save report to S3
        report_key = f"reports/{date_str}/report.html"
        save_report_to_s3(html_report, batch_result, bucket, report_key, date_str)
        
        # Send via email
        email_success = send_via_email(html_report, date_str)
        
        logger.info(f"Successfully generated and sent report")
        
        return {
            'statusCode': 200,
            'date': date_str,
            'bucket': bucket,
            'report_key': report_key,
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
        
        # Log the structure to help debug
        logger.info(f"Full result keys: {list(full_result.keys()) if isinstance(full_result, dict) else 'Not a dict'}")
        
        # Try to extract parsed_result first
        if 'parsed_result' in full_result:
            logger.info(f"Parsed result keys: {list(full_result['parsed_result'].keys()) if isinstance(full_result['parsed_result'], dict) else 'Not a dict'}")
            return full_result.get('parsed_result', {})
        
        # If no parsed_result, return the full result
        return full_result
        
    except Exception as e:
        logger.error(f"Failed to load batch results from s3://{bucket}/{key}: {e}")
        raise


def extract_openai_report(batch_result: Dict[str, Any]) -> str:
    """
    Extract the HTML report from OpenAI response or generate from data.
    
    Args:
        batch_result: Parsed batch result dictionary from OpenAI
        
    Returns:
        HTML report string
    """
    try:
        logger.info(f"Processing batch_result type: {type(batch_result)}")
        logger.info(f"Processing batch_result keys: {list(batch_result.keys()) if isinstance(batch_result, dict) else 'Not a dict'}")
        
        # If batch_result is a string that looks like JSON, parse it
        if isinstance(batch_result, str):
            try:
                batch_result = json.loads(batch_result)
                logger.info(f"Parsed string to dict with keys: {list(batch_result.keys())}")
            except json.JSONDecodeError:
                # If it's not JSON but contains HTML, return it
                if '<html' in batch_result.lower():
                    logger.info("Found HTML content as string")
                    return batch_result
        
        # Check if OpenAI returned HTML report directly
        if isinstance(batch_result, dict) and 'html_report' in batch_result:
            logger.info("Found html_report field")
            return batch_result['html_report']
            
        # Check for content field with HTML
        if isinstance(batch_result, dict) and 'content' in batch_result:
            content = batch_result['content']
            if isinstance(content, str):
                # Check if content is HTML
                if '<html' in content.lower():
                    logger.info("Found HTML in content field")
                    return content
                # Check if content is JSON string containing listings
                try:
                    content_parsed = json.loads(content)
                    if 'listings' in content_parsed:
                        logger.info("Found listings in parsed content field")
                        return generate_html_from_data(content_parsed)
                except json.JSONDecodeError:
                    pass
        
        # If OpenAI returned structured data with listings
        if isinstance(batch_result, dict) and 'listings' in batch_result:
            logger.info("Found listings data, generating HTML report")
            # Validate that listings is actually a list
            listings = batch_result.get('listings', [])
            if not isinstance(listings, list):
                logger.warning(f"Listings is not a list: {type(listings)}")
                # Try to convert to list if it's a single item
                if isinstance(listings, dict):
                    listings = [listings]
                else:
                    listings = []
                batch_result['listings'] = listings
            return generate_html_from_data(batch_result)
        
        # Check for nested structures
        if isinstance(batch_result, dict):
            # Check if there's a 'response' field containing the actual data
            if 'response' in batch_result:
                return extract_openai_report(batch_result['response'])
            
            # Check if there's a 'body' field containing the actual data
            if 'body' in batch_result:
                return extract_openai_report(batch_result['body'])
                
            # Check if there's a 'result' field containing the actual data
            if 'result' in batch_result:
                return extract_openai_report(batch_result['result'])
        
        # If we can't find any usable data, return error message
        logger.error(f"Could not extract or generate HTML report from OpenAI response")
        logger.error(f"Full response: {json.dumps(batch_result, indent=2) if isinstance(batch_result, (dict, list)) else str(batch_result)}")
        return f"""<html>
<head>
    <meta charset="UTF-8">
    <title>Report Generation Error</title>
</head>
<body>
    <h1>Report Generation Error</h1>
    <p>Could not extract HTML report from OpenAI response.</p>
    <h2>Debug Information:</h2>
    <pre>{json.dumps(batch_result, indent=2, ensure_ascii=False) if isinstance(batch_result, (dict, list)) else str(batch_result)}</pre>
</body>
</html>"""
        
    except Exception as e:
        logger.error(f"Error extracting OpenAI report: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        return f"""<html>
<head>
    <meta charset="UTF-8">
    <title>Report Generation Error</title>
</head>
<body>
    <h1>Report Generation Error</h1>
    <p>Error extracting report: {str(e)}</p>
    <h2>Debug Information:</h2>
    <pre>{json.dumps(batch_result, indent=2, ensure_ascii=False) if isinstance(batch_result, (dict, list)) else str(batch_result)}</pre>
</body>
</html>"""


def generate_html_from_data(data: Dict[str, Any]) -> str:
    """
    Generate HTML report from structured data returned by OpenAI.
    
    Args:
        data: Structured data from OpenAI containing listings
        
    Returns:
        HTML report string
    """
    try:
        listings = data.get('listings', [])
        
        # Log the structure for debugging
        logger.info(f"Data type: {type(data)}")
        logger.info(f"Listings type: {type(listings)}")
        if listings:
            logger.info(f"First listing type: {type(listings[0])}")
            logger.info(f"First listing content: {listings[0]}")
        report_date = datetime.now().strftime('%Y-%m-%d')
        
        # Count valid listings (only count dicts that have required fields)
        valid_listings = []
        for l in listings:
            if isinstance(l, dict) and l.get('title') and l.get('price'):
                valid_listings.append(l)
            elif isinstance(l, str):
                try:
                    parsed = json.loads(l)
                    if isinstance(parsed, dict) and parsed.get('title') and parsed.get('price'):
                        valid_listings.append(parsed)
                except:
                    pass
        
        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Tokyo RE Analysis - {report_date}</title>
</head>
<body style="margin:0;padding:0;font-family:Arial,sans-serif;line-height:1.6;color:#1f2937;background-color:#f9fafb;">
    <table width="100%" cellpadding="0" cellspacing="0" style="background-color:#f9fafb;">
        <tr>
            <td align="center">
                <table width="600" cellpadding="0" cellspacing="0" style="background-color:#ffffff;margin:20px auto;">
                    <!-- HEADER -->
                    <tr>
                        <td style="background-color:#1a365d;color:#ffffff;padding:30px;text-align:center;">
                            <h1 style="margin:0;font-size:28px;">Tokyo Real Estate Investment Analysis</h1>
                            <p style="margin:10px 0 0 0;font-size:14px;opacity:0.9;">{report_date} | AI-Powered Analysis</p>
                        </td>
                    </tr>
                    
                    <!-- STATS BAR -->
                    <tr>
                        <td style="padding:20px;">
                            <table width="100%" cellpadding="0" cellspacing="0" style="background-color:#f7fafc;border-radius:8px;">
                                <tr>
                                    <td width="100%" style="padding:20px;text-align:center;">
                                        <div style="font-size:24px;font-weight:bold;color:#1a365d;">{len(valid_listings)}</div>
                                        <div style="font-size:12px;color:#4a5568;">Properties Analyzed</div>
                                    </td>
                                </tr>
                            </table>
                        </td>
                    </tr>
                    
                    <!-- PROPERTIES LIST -->
                    <tr>
                        <td style="padding:20px;">
                            <h2 style="margin:0 0 15px 0;color:#2d3748;font-size:20px;">Property Details</h2>
"""
        
        # Process each listing
        for i, listing in enumerate(listings, 1):
            # Handle case where listing might be a string (JSON) instead of dict
            if isinstance(listing, str):
                try:
                    listing = json.loads(listing)
                    logger.info(f"Parsed listing {i} from string to dict")
                except json.JSONDecodeError:
                    logger.error(f"Listing {i} is a string but not valid JSON: {listing}")
                    continue
            
            # Skip if listing is not a dictionary
            if not isinstance(listing, dict):
                logger.error(f"Listing {i} is not a dictionary: {type(listing)}")
                continue
            
            # Extract and clean data
            title = listing.get('title', f'Property {i}')
            price = listing.get('price', 'Price not available')
            building_area = listing.get('building_area', 'N/A')
            land_area = listing.get('land_area', 'N/A')
            location = listing.get('location', 'Location not specified')
            age = listing.get('age', 'Age not specified')
            structure = listing.get('structure', 'N/A')
            floor = listing.get('floor', 'N/A')
            balcony = listing.get('balcony', 'N/A')
            management_fee = listing.get('management_fee', 'N/A')
            seismic = listing.get('seismic', 'N/A')
            bcr_far = listing.get('bcr_far', 'N/A')
            dom = listing.get('dom', 'N/A')
            listing_url = listing.get('listing_url', '#')
            
            html += f"""
                            <table width="100%" cellpadding="15" cellspacing="0" style="background-color:#ffffff;border:1px solid #e2e8f0;margin-bottom:20px;border-radius:8px;">
                                <tr>
                                    <td>
                                        <h3 style="margin:0 0 10px 0;color:#2d3748;font-size:18px;">{title}</h3>
                                        <table width="100%" cellpadding="5" cellspacing="0" style="font-size:14px;">
                                            <tr><td style="color:#718096;width:150px;vertical-align:top;">Price:</td><td style="font-weight:bold;color:#e53e3e;">{price}</td></tr>
                                            <tr><td style="color:#718096;vertical-align:top;">Location:</td><td>{location}</td></tr>
                                            <tr><td style="color:#718096;vertical-align:top;">Building Area:</td><td>{building_area}</td></tr>
                                            <tr><td style="color:#718096;vertical-align:top;">Land Area:</td><td>{land_area}</td></tr>
                                            <tr><td style="color:#718096;vertical-align:top;">Age/Structure:</td><td>{age} / {structure}</td></tr>
                                            <tr><td style="color:#718096;vertical-align:top;">Floor/Balcony:</td><td>{floor} / {balcony}</td></tr>
                                            <tr><td style="color:#718096;vertical-align:top;">BCR/FAR:</td><td>{bcr_far}</td></tr>
                                            <tr><td style="color:#718096;vertical-align:top;">Management:</td><td>{management_fee}</td></tr>
                                            <tr><td style="color:#718096;vertical-align:top;">Seismic:</td><td>{seismic}</td></tr>
                                            <tr><td style="color:#718096;vertical-align:top;">Days on Market:</td><td>{dom}</td></tr>
                                        </table>
                                        <div style="margin-top:10px;">
                                            <a href="{listing_url}" style="color:#3182ce;text-decoration:none;font-size:12px;">View Listing →</a>
                                        </div>
                                    </td>
                                </tr>
                            </table>
"""
        
        # Add footer
        html += """
                        </td>
                    </tr>
                    
                    <!-- FOOTER -->
                    <tr>
                        <td style="padding:20px;background-color:#f7fafc;">
                            <p style="margin:0;font-size:12px;color:#718096;text-align:center;">
                                <strong>Generated by:</strong> Tokyo Real Estate AI Analysis System<br>
                                <strong>Data Source:</strong> OpenAI GPT Analysis<br>
                                <strong>Note:</strong> This report was generated from structured data provided by the AI model.
                            </p>
                        </td>
                    </tr>
                </table>
            </td>
        </tr>
    </table>
</body>
</html>"""
        
        logger.info(f"Successfully generated HTML report with {len(listings)} listings")
        return html
        
    except Exception as e:
        logger.error(f"Error generating HTML from data: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        return f"""<html>
<head>
    <meta charset="UTF-8">
    <title>Report Generation Error</title>
</head>
<body>
    <h1>Report Generation Error</h1>
    <p>Error generating HTML from data: {str(e)}</p>
    <h2>Data Structure:</h2>
    <pre>{json.dumps(data, indent=2, ensure_ascii=False)}</pre>
</body>
</html>"""


def format_currency(amount: float) -> str:
    """Format currency amount with commas."""
    try:
        return f"¥{int(amount):,}"
    except (ValueError, TypeError):
        return "¥0"


def save_report_to_s3(html_report: str, batch_result: Dict[str, Any], bucket: str, report_key: str, date_str: str) -> None:
    """
    Save report and results to S3.
    
    Args:
        html_report: HTML report content
        batch_result: Full batch result dictionary
        bucket: S3 bucket name
        report_key: S3 key for HTML report
        date_str: Processing date string
    """
    try:
        # Save HTML report
        s3_client.put_object(
            Bucket=bucket,
            Key=report_key,
            Body=html_report.encode('utf-8'),
            ContentType='text/html'
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



def send_via_email(html_report: str, date_str: str) -> bool:
    """
    Send report via SES email with enhanced debugging.
    
    Args:
        html_report: HTML report content
        date_str: Processing date string
        
    Returns:
        True if successful, False otherwise
    """
    try:
        email_from = os.environ.get('EMAIL_FROM')
        email_to = os.environ.get('EMAIL_TO')
        
        logger.info(f"Email configuration - FROM: {email_from}, TO: {email_to}")
        
        if not email_from or not email_to:
            logger.error("Email addresses not configured in environment variables")
            return False
        
        # Check SES verification status
        try:
            identity_verification = ses_client.get_identity_verification_attributes(
                Identities=[email_from, email_to]
            )
            logger.info(f"SES verification status: {identity_verification}")
        except Exception as e:
            logger.warning(f"Could not check SES verification status: {e}")
        
        # Convert HTML to plain text for email
        plain_text = html_to_plain_text(html_report)
        
        subject = f"Tokyo Real Estate Analysis - {date_str}"
        
        logger.info(f"Sending email with subject: {subject}")
        logger.info(f"Content length - Plain: {len(plain_text)}, HTML: {len(html_report)}")
        
        response = ses_client.send_email(
            Source=email_from,
            Destination={'ToAddresses': [email_to]},
            Message={
                'Subject': {
                    'Data': subject,
                    'Charset': 'UTF-8'
                },
                'Body': {
                    'Text': {
                        'Data': plain_text,
                        'Charset': 'UTF-8'
                    },
                    'Html': {
                        'Data': html_report,
                        'Charset': 'UTF-8'
                    }
                }
            }
        )
        
        logger.info(f"Successfully sent email: {response['MessageId']}")
        return True
        
    except Exception as e:
        logger.error(f"Failed to send email: {str(e)}")
        logger.error(f"Error type: {type(e).__name__}")
        # Log additional details for debugging
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        return False


def html_to_plain_text(html: str) -> str:
    """Convert HTML to plain text."""
    import re
    
    # Remove HTML tags while preserving content
    text = re.sub(r'<[^>]+>', '', html)
    
    # Convert HTML entities
    text = text.replace('&amp;', '&')
    text = text.replace('&lt;', '<')
    text = text.replace('&gt;', '>')
    text = text.replace('&quot;', '"')
    text = text.replace('&apos;', "'")
    text = text.replace('&nbsp;', ' ')
    text = text.replace('&rarr;', '→')
    
    # Clean up multiple whitespace
    text = re.sub(r'\s+', ' ', text)
    text = text.strip()
    
    return text


if __name__ == "__main__":
    # For local testing
    test_event = {
        'date': '2025-07-16',
        'bucket': 'tokyo-real-estate-ai-data',
        'result_key': 'batch_output/2025-07-16/response.json',
        'batch_result': {
            'listings': [
                {
                    'title': '物件ID: 12345 - 新宿区マンション',
                    'price': '¥2,800万円',
                    'building_area': '75m²',
                    'land_area': '-',
                    'price_per_m2': '-',
                    'age': '築15年',
                    'structure': 'RC',
                    'road_width': '5m',
                    'location': '新宿区西新宿',
                    'building_name': 'サンシャインマンション',
                    'floor': '3階/10階',
                    'balcony': '10m²',
                    'dom': '募集期間: 90日',
                    'bcr_far': '建ぺい率: 60% / 容積率: 200%',
                    'management_fee': '管理費: ¥15,000/月',
                    'seismic': '耐震基準適合',
                    'listing_url': 'https://example.com/12345'
                },
                {
                    'title': '物件ID: 67890 - 杉並区一戸建て',
                    'price': '¥2,500万円',
                    'building_area': '100m²',
                    'land_area': '100m²',
                    'price_per_m2': '-',
                    'age': '築25年',
                    'structure': '木造',
                    'road_width': '4.5m',
                    'location': '杉並区高円寺',
                    'building_name': '-',
                    'floor': '-',
                    'balcony': '-',
                    'dom': '募集期間: 120日',
                    'bcr_far': '建ぺい率: 50% / 容積率: 150%',
                    'management_fee': '-',
                    'seismic': '耐震基準適合',
                    'listing_url': 'https://example.com/67890'
                }
            ]
        }
    }
    
    # Test the extraction
    html = extract_openai_report(test_event['batch_result'])
    print(html)