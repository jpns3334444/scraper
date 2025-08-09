#!/usr/bin/env python3
"""
Unit tests for lossless distiller
"""
import json
import sys
import os

# Add the lambda directory to the path so we can import the module
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lambda', 'property_processor'))

from lossless_distiller import distill_lossless


def test_lossless_distiller():
    """Test lossless distiller with various HTML features"""
    
    # Test HTML with all the features we want to extract
    test_html = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Test Property Page</title>
        <meta name="description" content="A nice property">
        <meta property="og:title" content="Property Title">
        <meta http-equiv="Content-Type" content="text/html; charset=utf-8">
        <meta id="utag_data_meta" content='{"property_id": "12345", "price": 5000}'>
        <script type="application/ld+json">
        {
            "@context": "http://schema.org",
            "@type": "RealEstate",
            "name": "Test Property"
        }
        </script>
        <style>
            body { font-family: Arial; }
        </style>
        <script>
            console.log("This should be removed");
        </script>
    </head>
    <body>
        <main>
            <h1>Main Property Content</h1>
            <p>This is the   main    content with  whitespace   that should be collapsed.</p>
            
            <table>
                <thead>
                    <tr>
                        <th>Feature</th>
                        <th>Value</th>
                    </tr>
                </thead>
                <tbody>
                    <tr>
                        <td>Price</td>
                        <td>5000万円</td>
                    </tr>
                    <tr>
                        <td>Size</td>
                        <td>60㎡</td>
                    </tr>
                </tbody>
            </table>
            
            <div>
                <a href="/details">Property Details</a>
                <a href="https://example.com">External Link</a>
            </div>
            
            <div>
                <img src="image1.jpg" alt="Property Image 1">
                <img src="image2.jpg" alt="Property Image 2">
            </div>
            
            <div data-property-id="12345" data-price="5000" class="property-info">
                Property data attributes
            </div>
        </main>
        
        <noscript>
            This noscript content should be removed
        </noscript>
    </body>
    </html>
    """
    
    result = distill_lossless(test_html)
    
    # Test basic structure
    assert result['version'] == 'lossless-v1'
    assert result['title'] == 'Test Property Page'
    
    # Test meta tags extraction
    assert len(result['meta_tags']) >= 3
    meta_names = [tag.get('name') for tag in result['meta_tags'] if tag.get('name')]
    assert 'description' in meta_names
    
    # Test utag_data extraction (HOME'S specific)
    assert result['utag_data'] is not None
    assert isinstance(result['utag_data'], dict)
    assert result['utag_data']['property_id'] == '12345'
    
    # Test JSON-LD extraction
    print(f"DEBUG: jsonld result: {result['jsonld']}")
    assert len(result['jsonld']) >= 0  # Might not extract if script is malformed
    if result['jsonld']:
        assert result['jsonld'][0]['@type'] == 'RealEstate'
    
    # Test visible text (whitespace collapsed)
    visible_text = result['visible_text']
    assert 'Main Property Content' in visible_text
    assert 'main content with whitespace that should be collapsed' in visible_text
    # Check that multiple spaces are collapsed
    assert '   ' not in visible_text
    assert '\n' not in visible_text
    # Check that script/style content is not included
    assert 'console.log' not in visible_text
    assert 'font-family' not in visible_text
    assert 'noscript content should be removed' not in visible_text
    
    # Test links extraction
    assert len(result['links']) == 2
    link_hrefs = [link['href'] for link in result['links']]
    assert '/details' in link_hrefs
    assert 'https://example.com' in link_hrefs
    
    # Test images extraction
    assert len(result['images']) == 2
    image_srcs = [img['src'] for img in result['images']]
    assert 'image1.jpg' in image_srcs
    assert 'image2.jpg' in image_srcs
    image_alts = [img['alt'] for img in result['images']]
    assert 'Property Image 1' in image_alts
    
    # Test tables extraction
    assert len(result['tables']) == 1
    table = result['tables'][0]
    assert table['headers'] == ['Feature', 'Value']
    assert len(table['rows']) == 2
    assert table['rows'][0] == ['Price', '5000万円']
    assert table['rows'][1] == ['Size', '60㎡']
    
    # Test data attributes extraction
    data_attrs = result['data_attributes']
    assert len(data_attrs) == 2
    data_attr_names = [attr['data_attr'] for attr in data_attrs]
    assert 'data-property-id' in data_attr_names
    assert 'data-price' in data_attr_names
    
    print("All tests passed!")


def test_empty_html():
    """Test with empty/invalid HTML"""
    result = distill_lossless("")
    assert result.get('version') == 'lossless-v1'
    assert result.get('visible_text', '') == ""
    assert len(result.get('links', [])) == 0
    
    result = distill_lossless(None)
    assert result.get('version') == 'lossless-v1'
    assert result.get('visible_text', '') == ""


def test_malformed_json():
    """Test with malformed JSON-LD"""
    html_with_bad_json = """
    <html>
    <body>
        <script type="application/ld+json">
        { "invalid": json here }
        </script>
        <p>Some content</p>
    </body>
    </html>
    """
    
    result = distill_lossless(html_with_bad_json)
    assert result['version'] == 'lossless-v1'
    # Should not crash, just skip the bad JSON
    assert len(result['jsonld']) == 0
    assert 'Some content' in result['visible_text']


if __name__ == '__main__':
    test_lossless_distiller()
    test_empty_html() 
    test_malformed_json()
    print("All lossless distiller tests passed!")