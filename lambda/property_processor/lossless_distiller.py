#!/usr/bin/env python3
"""
Lossless-ish HTML distiller for property pages.
Removes only code (script/style/noscript), retains everything the LLM may need.
"""
import re
import json
import hashlib
from datetime import datetime
from bs4 import BeautifulSoup


def _collapse_ws(s: str) -> str:
    """Collapse whitespace sequences to single spaces"""
    if not s:
        return ""
    return re.sub(r'\s+', ' ', s).strip()


def _serialize_table(table_tag) -> dict:
    """Serialize table element to structured format"""
    headers = []
    rows = []
    
    # Try to find headers from thead
    thead = table_tag.find('thead')
    if thead:
        th_tags = thead.find_all(['th', 'td'])
        headers = [_collapse_ws(th.get_text()) for th in th_tags]
    
    # If no thead, try first row as headers
    if not headers:
        first_row = table_tag.find('tr')
        if first_row:
            th_tags = first_row.find_all('th')
            if th_tags:
                headers = [_collapse_ws(th.get_text()) for th in th_tags]
    
    # Get all table rows (including tbody if present)
    tbody = table_tag.find('tbody')
    if tbody:
        tr_tags = tbody.find_all('tr')
    else:
        tr_tags = table_tag.find_all('tr')
    
    for tr in tr_tags:
        # Skip header row if we already extracted headers from it
        if headers and tr == table_tag.find('tr') and tr.find('th'):
            continue
            
        cells = tr.find_all(['td', 'th'])
        if cells:
            row_data = [_collapse_ws(cell.get_text()) for cell in cells]
            if any(cell.strip() for cell in row_data):  # Skip empty rows
                rows.append(row_data)
    
    return {
        "headers": headers,
        "rows": rows
    }


def distill_lossless(html: str, base_node_selector: str = None) -> dict:
    """
    Extract lossless-ish structured data from HTML.
    
    Args:
        html: Raw HTML content
        base_node_selector: Optional CSS selector for main content area
    
    Returns:
        Dict with structured content
    """
    if not html:
        return {
            "version": "lossless-v1",
            "title": "",
            "meta_tags": [],
            "utag_data": None,
            "jsonld": [],
            "visible_text": "",
            "links": [],
            "images": [],
            "tables": [],
            "data_attributes": []
        }
    
    try:
        soup = BeautifulSoup(html, 'html.parser')
        
        # Remove script, style, noscript tags completely
        for tag in soup(['script', 'style', 'noscript']):
            tag.decompose()
        
        # Find main content node
        main_node = None
        if base_node_selector:
            main_node = soup.select_one(base_node_selector)
        
        if not main_node:
            # Try common main content selectors
            for selector in ['main', 'article', 'body']:
                main_node = soup.find(selector)
                if main_node:
                    break
        
        if not main_node:
            main_node = soup
        
        # Extract title
        title = ""
        title_tag = soup.find('title')
        if title_tag:
            title = _collapse_ws(title_tag.get_text())
        
        # Extract all meta tags
        meta_tags = []
        for meta in soup.find_all('meta'):
            meta_data = {}
            for attr in ['name', 'property', 'http-equiv', 'content', 'id']:
                if meta.get(attr):
                    meta_data[attr] = meta.get(attr)
            if meta_data:
                meta_tags.append(meta_data)
        
        # Extract utag_data_meta (HOME'S specific)
        utag_data = None
        utag_meta = soup.find('meta', id='utag_data_meta')
        if utag_meta and utag_meta.get('content'):
            try:
                utag_data = json.loads(utag_meta.get('content'))
            except json.JSONDecodeError:
                utag_data = utag_meta.get('content')
        
        # Extract JSON-LD
        jsonld = []
        for script in soup.find_all('script'):
            script_type = script.get('type', '')
            if 'ld+json' in script_type.lower():
                try:
                    script_content = script.string or script.get_text()
                    if script_content:
                        script_content = script_content.strip()
                        parsed_json = json.loads(script_content)
                        jsonld.append(parsed_json)
                except (json.JSONDecodeError, AttributeError):
                    pass
        
        # Extract visible text from main content
        visible_text = _collapse_ws(main_node.get_text(separator=' ', strip=True))
        
        # Extract links from main content
        links = []
        for a_tag in main_node.find_all('a'):
            href = a_tag.get('href')
            text = _collapse_ws(a_tag.get_text())
            if href or text:
                links.append({
                    "text": text,
                    "href": href
                })
        
        # Extract images from main content
        images = []
        for img_tag in main_node.find_all('img'):
            alt = img_tag.get('alt')
            src = img_tag.get('src') or img_tag.get('data-src')
            if alt or src:
                images.append({
                    "alt": alt,
                    "src": src
                })
        
        # Extract tables from main content
        tables = []
        for table_tag in main_node.find_all('table'):
            table_data = _serialize_table(table_tag)
            if table_data['headers'] or table_data['rows']:
                tables.append(table_data)
        
        # Extract data-* attributes from main content
        data_attributes = []
        for element in main_node.find_all(True):  # All tags
            for attr_name, attr_value in element.attrs.items():
                if attr_name.startswith('data-'):
                    data_attributes.append({
                        "tag": element.name,
                        "data_attr": attr_name,
                        "value": str(attr_value) if attr_value else ""
                    })
        
        return {
            "version": "lossless-v1",
            "title": title,
            "meta_tags": meta_tags,
            "utag_data": utag_data,
            "jsonld": jsonld,
            "visible_text": visible_text,
            "links": links,
            "images": images,
            "tables": tables,
            "data_attributes": data_attributes
        }
        
    except Exception as e:
        # Return as much as possible, never raise
        return {
            "version": "lossless-v1",
            "title": "",
            "meta_tags": [],
            "utag_data": None,
            "jsonld": [],
            "visible_text": "",
            "links": [],
            "images": [],
            "tables": [],
            "data_attributes": [],
            "extraction_error": str(e)
        }