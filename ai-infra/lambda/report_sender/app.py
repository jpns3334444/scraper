"""
Report Sender Lambda function for generating and delivering HTML reports.
Processes LLM results and sends via SES email.
"""
import json
import os
from datetime import datetime
from typing import Any, Dict, List
from urllib.parse import urlparse
from pathlib import Path

import boto3
from jinja2 import Environment, FileSystemLoader, Template

# Import our structured logger
try:
    from common.logger import get_logger, lambda_log_context
    logger = get_logger(__name__)
except ImportError:
    import logging
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
    Extract and combine HTML email reports from all successful OpenAI responses.
    
    The response for each item is expected to be a JSON string
    containing 'database_fields' and 'email_report'.
    This function extracts all 'email_report' entries and combines them.
    """
    try:
        individual_results = batch_result.get('individual_results', [])
        logger.info(f"Found {len(individual_results)} individual results to process.")

        successful_reports = []
        failed_properties = []

        for result in individual_results:
            custom_id = result.get('custom_id', 'unknown')
            # The 'analysis' field should contain the JSON string from the LLM
            analysis_str = result.get('analysis', '{}')
            if not analysis_str or not analysis_str.strip():
                logger.warning(f"Skipping result with empty analysis content: {custom_id}")
                failed_properties.append(custom_id)
                continue

            try:
                # Clean the analysis string - remove markdown code blocks if present
                cleaned_analysis = analysis_str.strip()
                if cleaned_analysis.startswith('```json'):
                    # Remove ```json from start and ``` from end
                    cleaned_analysis = cleaned_analysis[7:]  # Remove ```json
                    if cleaned_analysis.endswith('```'):
                        cleaned_analysis = cleaned_analysis[:-3]  # Remove ```
                    cleaned_analysis = cleaned_analysis.strip()
                elif cleaned_analysis.startswith('```'):
                    # Remove ``` from start and end
                    cleaned_analysis = cleaned_analysis[3:]
                    if cleaned_analysis.endswith('```'):
                        cleaned_analysis = cleaned_analysis[:-3]
                    cleaned_analysis = cleaned_analysis.strip()
                
                # Parse the JSON string to get to the email report
                analysis_json = json.loads(cleaned_analysis)
                
                # The email report is a top-level key in the parsed JSON
                if 'email_report' in analysis_json and analysis_json['email_report']:
                    logger.info(f"Successfully extracted email_report from {custom_id}")
                    successful_reports.append({
                        'property_id': custom_id,
                        'html_content': analysis_json['email_report']
                    })
                else:
                    logger.warning(f"No 'email_report' key found in analysis for {custom_id}")
                    failed_properties.append(custom_id)

            except json.JSONDecodeError as e:
                logger.error(f"Failed to decode analysis JSON for {custom_id}: {e}")
                logger.error(f"Problematic JSON string: {analysis_str[:500]}") # Log first 500 chars
                failed_properties.append(custom_id)
                continue

        # Combine all successful reports into one comprehensive email
        if successful_reports:
            combined_html = generate_combined_report(successful_reports, failed_properties, batch_result.get('batch_id', 'unknown'))
            logger.info(f"Successfully combined {len(successful_reports)} property reports into comprehensive email")
            return combined_html
    
    except Exception as e:
        logger.error(f"An unexpected error occurred while extracting the report: {e}")

    # Fallback if no email report is found in any of the results
    logger.error("Could not extract or generate HTML report from any OpenAI response.")
    return f"""<html>
<head>
    <meta charset="UTF-8">
    <title>Report Generation Error</title>
</head>
<body>
    <h1>Report Generation Error</h1>
    <p>Could not find a valid 'email_report' in any of the LLM responses.</p>
    <h2>Debug Information:</h2>
    <pre>{json.dumps(batch_result, indent=2, ensure_ascii=False)}</pre>
</body>
</html>"""


def load_email_template() -> Template:
    """
    Load the Jinja2 email template.
    
    Returns:
        Jinja2 Template object
    """
    try:
        # Try to load from file in same directory
        template_file = Path(__file__).parent / 'email_template.html'
        if template_file.exists():
            template_content = template_file.read_text(encoding='utf-8')
            return Template(template_content)
        
        # Fallback template if file not found
        logger.warning("email_template.html not found, using fallback template")
        fallback_template = """
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <title>Tokyo Real Estate Analysis Report</title>
        </head>
        <body>
            <h1>Tokyo Real Estate Investment Analysis Report</h1>
            <p>Generated: {{ report_date }} | Batch: {{ batch_id }}</p>
            
            <h2>Summary</h2>
            <p>Properties Successfully Analyzed: {{ successful_count }}</p>
            <p>Properties with Processing Issues: {{ failed_count }}</p>
            
            {% if failed_properties %}
            <h3>Processing Issues</h3>
            <ul>
                {% for prop_id in failed_properties %}
                <li>{{ prop_id }}</li>
                {% endfor %}
            </ul>
            {% endif %}
            
            <h2>Property Reports</h2>
            {% for report in property_reports %}
            <div style="margin-bottom: 30px; border: 1px solid #ddd; padding: 20px;">
                <h3>Property: {{ report.property_id }}</h3>
                {{ report.html_content | safe }}
            </div>
            {% endfor %}
        </body>
        </html>
        """
        return Template(fallback_template)
        
    except Exception as e:
        logger.error(f"Failed to load email template: {e}")
        # Return minimal template as last resort
        return Template('<html><body><h1>Report Error</h1><p>{{ error_message }}</p></body></html>')


def generate_combined_report(successful_reports: List[Dict[str, Any]], failed_properties: List[str], batch_id: str) -> str:
    """
    Generate a comprehensive HTML report using Jinja2 templating.
    
    Args:
        successful_reports: List of dicts with property_id and html_content
        failed_properties: List of property IDs that failed processing
        batch_id: Batch processing ID
        
    Returns:
        Combined HTML report string using Jinja2 template
    """
    try:
        # Load the email template
        template = load_email_template()
        
        # Prepare template data
        current_date = datetime.now().strftime("%Y-%m-%d %H:%M JST")
        
        # Process property reports for template
        processed_reports = []
        strong_buy_count = 0
        buy_count = 0
        
        for report in successful_reports:
            property_id = report['property_id'].split('-')[-1]  # Extract just the property ID
            html_content = report['html_content']
            
            # Extract the main content from individual report (remove outer html/head/body tags)
            import re
            body_match = re.search(r'<body[^>]*>(.*?)</body>', html_content, re.DOTALL | re.IGNORECASE)
            if body_match:
                content = body_match.group(1)
            else:
                content = html_content
            
            # Try to extract recommendation for counting
            if 'strong_buy' in html_content.lower() or 'strong buy' in html_content.lower():
                strong_buy_count += 1
            elif 'buy' in html_content.lower() and 'strong' not in html_content.lower():
                buy_count += 1
            
            processed_reports.append({
                'property_id': property_id,
                'html_content': content
            })
        
        # Generate market insights summary
        market_insights = generate_market_insights(successful_reports, failed_properties)
        
        # Template data
        template_data = {
            'report_date': current_date,
            'batch_id': batch_id,
            'successful_count': len(successful_reports),
            'failed_count': len(failed_properties),
            'strong_buy_count': strong_buy_count,
            'buy_count': buy_count,
            'failed_properties': failed_properties,
            'property_reports': processed_reports,
            'market_insights': market_insights
        }
        
        # Render template
        rendered_html = template.render(template_data)
        
        logger.info(f"Successfully rendered email template with {len(successful_reports)} properties")
        return rendered_html
        
    except Exception as e:
        logger.error(f"Failed to generate combined report with Jinja2: {e}")
        # Fallback to simple HTML generation
        return generate_fallback_report(successful_reports, failed_properties, batch_id)


def generate_market_insights(successful_reports: List[Dict[str, Any]], failed_properties: List[str]) -> str:
    """
    Generate market insights summary from the analysis results.
    
    Args:
        successful_reports: List of successful property analyses
        failed_properties: List of failed property IDs
        
    Returns:
        HTML string with market insights
    """
    try:
        total_analyzed = len(successful_reports)
        if total_analyzed == 0:
            return "<p>No properties were successfully analyzed to generate market insights.</p>"
        
        # Basic analysis of the reports
        insights = []
        
        # Processing success rate
        total_processed = total_analyzed + len(failed_properties)
        success_rate = (total_analyzed / total_processed * 100) if total_processed > 0 else 0
        
        insights.append(f"<li><strong>Processing Success Rate:</strong> {success_rate:.1f}% ({total_analyzed} of {total_processed} properties successfully analyzed)</li>")
        
        # Count recommendations (basic text analysis)
        recommendations = {'strong_buy': 0, 'buy': 0, 'hold': 0, 'pass': 0}
        for report in successful_reports:
            content = report.get('html_content', '').lower()
            if 'strong_buy' in content or 'strong buy' in content:
                recommendations['strong_buy'] += 1
            elif 'buy' in content and 'strong' not in content:
                recommendations['buy'] += 1
            elif 'hold' in content:
                recommendations['hold'] += 1
            elif 'pass' in content:
                recommendations['pass'] += 1
        
        if recommendations['strong_buy'] > 0:
            insights.append(f"<li><strong>Strong Buy Opportunities:</strong> {recommendations['strong_buy']} properties identified as exceptional investment opportunities</li>")
        
        if recommendations['buy'] > 0:
            insights.append(f"<li><strong>Buy Recommendations:</strong> {recommendations['buy']} properties showing good investment potential</li>")
        
        # Analysis quality
        if len(failed_properties) > 0:
            insights.append(f"<li><strong>Data Quality:</strong> {len(failed_properties)} properties had processing issues, possibly due to incomplete data or formatting challenges</li>")
        
        if not insights:
            insights.append("<li>Market analysis completed successfully with standard processing results.</li>")
        
        return f"""
        <ul>
            {''.join(insights)}
        </ul>
        <p style="margin-top: 15px; font-style: italic; color: #666;">
            This analysis is based on AI processing of property data and images. 
            Individual property reports contain detailed investment assessments and recommendations.
        </p>
        """
        
    except Exception as e:
        logger.error(f"Failed to generate market insights: {e}")
        return "<p>Market insights could not be generated due to processing error.</p>"


def generate_fallback_report(successful_reports: List[Dict[str, Any]], failed_properties: List[str], batch_id: str) -> str:
    """
    Generate a simple fallback report when Jinja2 templating fails.
    
    Args:
        successful_reports: List of successful property analyses
        failed_properties: List of failed property IDs
        batch_id: Batch processing ID
        
    Returns:
        Simple HTML report string
    """
    current_date = datetime.now().strftime("%Y-%m-%d %H:%M JST")
    
    # Extract individual property content
    property_sections = []
    for report in successful_reports:
        property_id = report['property_id'].split('-')[-1]
        html_content = report['html_content']
        
        property_sections.append(f"""
        <div style="margin-bottom: 30px; border: 1px solid #ddd; padding: 20px; border-radius: 8px; background: white;">
            <h3 style="color: #2c3e50; border-bottom: 2px solid #3498db; padding-bottom: 10px;">
                Property Analysis: {property_id}
            </h3>
            {html_content}
        </div>
        """)
    
    # Build failure summary
    failure_section = ""
    if failed_properties:
        failed_ids = [prop_id.split('-')[-1] for prop_id in failed_properties]
        failure_section = f"""
        <div style="margin-bottom: 30px; padding: 15px; background-color: #fff3cd; border: 1px solid #ffeaa7; border-radius: 8px;">
            <h3 style="color: #856404;">⚠️ Processing Issues</h3>
            <p>The following properties could not be fully analyzed:</p>
            <ul>{''.join(f'<li>{prop_id}</li>' for prop_id in failed_ids)}</ul>
        </div>
        """
    
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <title>Tokyo Real Estate Investment Analysis Report</title>
        <style>
            body {{ font-family: Arial, sans-serif; line-height: 1.6; margin: 0; padding: 20px; background-color: #f8f9fa; }}
            .header {{ background: linear-gradient(135deg, #1a365d 0%, #2c5282 100%); color: white; padding: 30px; text-align: center; border-radius: 8px; margin-bottom: 30px; }}
            .summary {{ background-color: white; padding: 20px; border-radius: 8px; margin-bottom: 30px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
        </style>
    </head>
    <body>
        <div class="header">
            <h1>Tokyo Real Estate Investment Analysis Report</h1>
            <p>Generated: {current_date} | Batch: {batch_id}</p>
        </div>
        
        <div class="summary">
            <h2>Analysis Summary</h2>
            <p><strong>Properties Successfully Analyzed:</strong> {len(successful_reports)}</p>
            <p><strong>Properties with Processing Issues:</strong> {len(failed_properties)}</p>
            <p><strong>Total Properties Processed:</strong> {len(successful_reports) + len(failed_properties)}</p>
        </div>
        
        {failure_section}
        
        <div>
            {''.join(property_sections)}
        </div>
        
        <div style="text-align: center; margin-top: 40px; padding: 20px; color: #666;">
            <p>Tokyo Real Estate AI Analysis System</p>
            <p>For investment guidance only. Conduct independent due diligence before making investment decisions.</p>
        </div>
    </body>
    </html>
    """


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
        'result_key': 'ai/results/2025-07-16/response.json',
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