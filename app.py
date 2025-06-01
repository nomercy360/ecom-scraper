from flask import Flask, request, jsonify
from seleniumbase import SB
from flask_cors import CORS
from flask_caching import Cache
import os
import json
from google import genai
from google.genai import types

app = Flask(__name__)
CORS(app)  # Allow all CORS requests for now

app.config['CACHE_TYPE'] = 'SimpleCache'
app.config['CACHE_DEFAULT_TIMEOUT'] = 300  # Cache timeout in seconds
cache = Cache(app)


def clean_url(url):
    if not url:
        return ""
    return url.strip()


def is_valid_url(url):
    if not url:
        return False

    return url.startswith('http://') or url.startswith('https://')


def extract_metadata(sb):
    """Extract metadata using JavaScript."""
    metadata = sb.execute_cdp_cmd("Runtime.evaluate", {
        "expression": """
            (() => {
                const metaTags = document.querySelectorAll('meta[property^="og:"], meta[name]');
                const metadata = {};
                metaTags.forEach(meta => {
                    const key = meta.getAttribute('property') || meta.getAttribute('name');
                    const value = meta.getAttribute('content');
                    if (key && value) {
                        metadata[key] = value;
                    }
                });
                return metadata;
            })();
        """,
        "returnByValue": True
    })["result"]["value"]
    return metadata


def clean_image_urls(image_urls, base_url):
    """Remove duplicates and convert relative URLs to absolute URLs."""
    cleaned_urls = set()
    for url in image_urls:
        if not url:
            continue
            
        # Strip any URL parameters or fragments
        clean_url = url.split('?')[0].split('#')[0]
        
        # Handle absolute URLs
        if clean_url.startswith("https://") or clean_url.startswith("http://"):
            cleaned_urls.add(clean_url)
        # Handle relative URLs
        elif clean_url.startswith("/"):
            domain = "/".join(base_url.split("/")[:3])
            cleaned_urls.add(f"{domain}{clean_url}")
        # Handle protocol-relative URLs
        elif clean_url.startswith("//"):
            cleaned_urls.add(f"https:{clean_url}")
        # Handle relative URLs without leading slash
        elif not clean_url.startswith(("http://", "https://", "/", "//")):
            # Extract base directory from URL
            base_dir = "/".join(base_url.split("/")[:-1]) + "/"
            cleaned_urls.add(f"{base_dir}{clean_url}")
    return list(cleaned_urls)


def clean_html_for_ai(sb):
    """Extract only relevant HTML content for AI processing, removing scripts, styles, etc."""
    cleaned_html = sb.execute_cdp_cmd("Runtime.evaluate", {
        "expression": """
            (() => {
                // Clone the document to avoid modifying the actual page
                const clonedDoc = document.cloneNode(true);
                
                // Remove script tags
                const scripts = clonedDoc.querySelectorAll('script');
                scripts.forEach(script => script.remove());
                
                // Remove style tags
                const styles = clonedDoc.querySelectorAll('style');
                styles.forEach(style => style.remove());
                
                // Remove link tags (stylesheets)
                const links = clonedDoc.querySelectorAll('link[rel="stylesheet"]');
                links.forEach(link => link.remove());
                
                // Remove comments
                const removeComments = (node) => {
                    for (let i = node.childNodes.length - 1; i >= 0; i--) {
                        const child = node.childNodes[i];
                        if (child.nodeType === 8) { // Comment node
                            child.remove();
                        } else if (child.nodeType === 1) { // Element node
                            removeComments(child);
                        }
                    }
                };
                removeComments(clonedDoc);
                
                // Remove common non-content elements
                const selectorsToRemove = [
                    'iframe',
                    'noscript',
                    'svg:not([data-product-image])', // Keep product image SVGs
                    'path',
                    'defs',
                    '.analytics-*',
                    '[class*="tracking"]',
                    '[class*="analytics"]',
                    '[id*="tracking"]',
                    '[id*="analytics"]',
                    '.cookie-*',
                    '[class*="cookie"]',
                    '.gdpr-*',
                    '[class*="gdpr"]',
                    'footer',
                    'header nav', // Keep header but remove navigation
                    '.navigation',
                    '.menu',
                    '.sidebar:not(.product-sidebar)',
                    '.advertisement',
                    '.ads',
                    '[class*="banner"]:not([class*="product"])',
                    '.popup',
                    '.modal:not(.product-modal)',
                    '.overlay:not(.product-overlay)',
                    '.social-share',
                    '.social-media',
                    '[class*="facebook"]',
                    '[class*="twitter"]',
                    '[class*="instagram"]',
                    '[class*="pinterest"]',
                    '.newsletter',
                    '.subscription',
                    '.related-products',
                    '.recommended-products',
                    '.recently-viewed',
                    '.reviews:not(.product-reviews)',
                    '.comments:not(.product-comments)',
                    '.chat-widget',
                    '[id*="chat"]',
                    '.help-widget'
                ];
                
                selectorsToRemove.forEach(selector => {
                    try {
                        const elements = clonedDoc.querySelectorAll(selector);
                        elements.forEach(el => el.remove());
                    } catch (e) {
                        // Ignore selector errors
                    }
                });
                
                // Remove all inline styles and unnecessary attributes
                const allElements = clonedDoc.querySelectorAll('*');
                allElements.forEach(el => {
                    el.removeAttribute('style');
                    el.removeAttribute('onclick');
                    el.removeAttribute('onload');
                    el.removeAttribute('onerror');
                    el.removeAttribute('onmouseover');
                    el.removeAttribute('onmouseout');
                    el.removeAttribute('data-analytics');
                    el.removeAttribute('data-tracking');
                    
                    // Remove data attributes except for product-related ones
                    const attrs = Array.from(el.attributes);
                    attrs.forEach(attr => {
                        if (attr.name.startsWith('data-') && 
                            !attr.name.includes('product') && 
                            !attr.name.includes('price') && 
                            !attr.name.includes('image') &&
                            !attr.name.includes('name') &&
                            !attr.name.includes('sku') &&
                            !attr.name.includes('currency')) {
                            el.removeAttribute(attr.name);
                        }
                    });
                });
                
                // Keep only essential HTML structure with product-related content
                let html = clonedDoc.documentElement.outerHTML;
                
                // Remove excessive whitespace
                html = html.replace(/\s+/g, ' ').replace(/> </g, '><').trim();
                
                // Limit the HTML size (take first 50KB)
                const maxLength = 50000;
                if (html.length > maxLength) {
                    // Try to find the main product container first
                    const productSelectors = [
                        '.product-container',
                        '.product-details',
                        '.product-info',
                        '.product-main',
                        '[class*="product-page"]',
                        '[id*="product-container"]',
                        'main[role="main"]',
                        'main',
                        '.content',
                        '#content'
                    ];
                    
                    for (const selector of productSelectors) {
                        const productElement = clonedDoc.querySelector(selector);
                        if (productElement) {
                            html = productElement.outerHTML;
                            if (html.length <= maxLength) {
                                break;
                            }
                        }
                    }
                    
                    // If still too long, truncate
                    if (html.length > maxLength) {
                        html = html.substring(0, maxLength) + '...';
                    }
                }
                
                return html;
            })();
        """,
        "returnByValue": True,
    })["result"]["value"]
    
    return cleaned_html


def extract_product_info_from_html(html_content):
    """Extract product information from HTML using Google Gemini AI."""
    try:
        client = genai.Client(
            api_key=os.getenv("GOOGLE_GENAI_API_KEY", ""),
        )

        model = "gemini-2.5-flash-preview-05-20"
        
        # Prepare the content for the AI model with cleaned HTML
        contents = [
            types.Content(
                role="user",
                parts=[
                    types.Part.from_text(text=f'Extract from html: product price if available, currency code (ISO 4217), product images, product name:\n{html_content}'),
                ],
            ),
        ]
        
        generate_content_config = types.GenerateContentConfig(
            thinking_config=types.ThinkingConfig(
                thinking_budget=0,
            ),
            response_mime_type="application/json",
            response_schema=genai.types.Schema(
                type=genai.types.Type.OBJECT,
                required=["product_name"],
                properties={
                    "price": genai.types.Schema(
                        type=genai.types.Type.NUMBER,
                    ),
                    "currency_code": genai.types.Schema(
                        type=genai.types.Type.STRING,
                    ),
                    "product_name": genai.types.Schema(
                        type=genai.types.Type.STRING,
                    ),
                    "images": genai.types.Schema(
                        type=genai.types.Type.ARRAY,
                        items=genai.types.Schema(
                            type=genai.types.Type.STRING,
                        ),
                    ),
                },
            ),
        )

        # Generate content from the AI model
        response_text = ""
        usage_metadata = None
        
        # Use non-streaming to get usage metadata
        response = client.models.generate_content(
            model=model,
            contents=contents,
            config=generate_content_config,
        )
        
        # Extract text and usage metadata
        response_text = response.text
        usage_metadata = response.usage_metadata if hasattr(response, 'usage_metadata') else None
        
        # Parse the JSON response
        result = json.loads(response_text)
        
        # Add token usage information if available
        if usage_metadata:
            result['_token_usage'] = {
                'prompt_tokens': getattr(usage_metadata, 'prompt_token_count', None),
                'completion_tokens': getattr(usage_metadata, 'candidates_token_count', None),
                'total_tokens': getattr(usage_metadata, 'total_token_count', None)
            }
            
            # Estimate cost (Gemini pricing as of 2024)
            # Gemini 1.5 Flash: $0.075 per 1M input tokens, $0.30 per 1M output tokens
            if result['_token_usage']['prompt_tokens'] and result['_token_usage']['completion_tokens']:
                input_cost = (result['_token_usage']['prompt_tokens'] / 1_000_000) * 0.075
                output_cost = (result['_token_usage']['completion_tokens'] / 1_000_000) * 0.30
                result['_token_usage']['estimated_cost_usd'] = round(input_cost + output_cost, 6)
                print(f"AI Token Usage - Input: {result['_token_usage']['prompt_tokens']}, "
                      f"Output: {result['_token_usage']['completion_tokens']}, "
                      f"Cost: ${result['_token_usage']['estimated_cost_usd']:.6f}")
        
        return result
    except Exception as e:
        print(f"Error extracting product info with AI: {e}")
        return None


@app.route('/extract-content', methods=['POST'])
def extract_content():
    data = request.json
    url = data.get("url")
    use_ai = data.get("use_ai", True)  # Default to using AI

    if not url:
        return jsonify({"error": "URL is required"}), 400

    url = clean_url(url)

    if not is_valid_url(url):
        return jsonify({"error": "Invalid URL format. URL must start with http:// or https://"}), 400

    # Check cache for existing response
    cache_key = f"content_{url}_{use_ai}"
    cached_response = cache.get(cache_key)
    if cached_response:
        return jsonify(cached_response), 200

    try:
        with SB(uc=True, test=True, locale_code="en", pls="none", headless=True) as sb:
            sb.activate_cdp_mode(url)
            sb.execute_cdp_cmd(
                'Network.setBlockedURLs',
                {"urls": [
                    "*.css",  # Stylesheets
                    "*.woff", "*.woff2", "*.ttf", "*.eot",  # Fonts
                    "*.mp4", "*.webm", "*.ogg", "*.mkv",  # Videos
                    "*googlesyndication.com*", "*doubleclick.net*",  # Ads
                    "*facebook.net*", "*analytics*", "*disqus.com*",  # Trackers & widgets
                    "*.gif", "*.1x1.png"  # Tracking pixels
                ]})
            sb.execute_cdp_cmd('Network.enable', {})

            sb.wait_for_ready_state_complete(timeout=10)

            # Wait until lazy loading images are loaded
            sb.sleep(2)

            if use_ai:
                # Get cleaned HTML content for AI processing
                html_content = clean_html_for_ai(sb)
                
                # Log the size reduction for debugging
                print(f"HTML size for AI: {len(html_content)} characters")
                
                # Extract product info using AI
                product_info = extract_product_info_from_html(html_content)
                
                if product_info:
                    response = {
                        "product_name": product_info.get("product_name"),
                        "price": product_info.get("price"),
                        "currency": product_info.get("currency_code"),
                        "image_urls": clean_image_urls(product_info.get("images", []), url),
                        "metadata": extract_metadata(sb),
                        "extracted_with": "ai"
                    }
                    
                    # Include token usage if available
                    if "_token_usage" in product_info:
                        response["token_usage"] = product_info["_token_usage"]
                else:
                    # Fallback to manual extraction if AI fails
                    images = sb.execute_cdp_cmd("Runtime.evaluate", {
                        "expression": """
                            function getBestSrcFromSrcset(srcset) {
                                if (!srcset) return null;
                                
                                // Parse the srcset attribute
                                const srcsetParts = srcset.split(',').map(part => {
                                    const [url, width] = part.trim().split(/\s+/);
                                    // Extract numeric width (remove the 'w')
                                    const numWidth = width ? parseInt(width.replace('w', '')) : 0;
                                    return { url, width: numWidth };
                                });
                                
                                // Sort by width (descending) and return the largest image
                                srcsetParts.sort((a, b) => b.width - a.width);
                                return srcsetParts.length > 0 ? srcsetParts[0].url : null;
                            }
                            
                            Array.from(document.querySelectorAll('img'))
                                .filter(img => {
                                    // Check if image is visible
                                    const rect = img.getBoundingClientRect();
                                    const style = window.getComputedStyle(img);
                                    
                                    // Minimum dimensions for non-icon/logo images (in pixels)
                                    const MIN_WIDTH = 100;
                                    const MIN_HEIGHT = 100;
                                    const MIN_AREA = 10000; // width * height
                                    
                                    // Calculate actual dimensions
                                    const area = rect.width * rect.height;
                                    
                                    return rect.width >= MIN_WIDTH && 
                                           rect.height >= MIN_HEIGHT && 
                                           area >= MIN_AREA &&
                                           style.display !== 'none' && 
                                           style.visibility !== 'hidden' &&
                                           parseFloat(style.opacity) > 0;
                                })
                                .flatMap(img => {
                                    const urls = [];
                                    
                                    // Get the src attribute
                                    if (img.src) {
                                        urls.push(img.src);
                                    }
                                    
                                    // Get the best image from srcset if available
                                    const srcset = img.getAttribute('srcset') || img.dataset.srcset;
                                    if (srcset) {
                                        const bestSrc = getBestSrcFromSrcset(srcset);
                                        if (bestSrc) {
                                            urls.push(bestSrc);
                                        }
                                    }
                                    
                                    return urls;
                                });
                        """,
                        "returnByValue": True,
                        "awaitPromise": True,
                    })["result"]["value"]

                    image_urls = clean_image_urls(images, url)
                    metadata = extract_metadata(sb)
                    
                    response = {
                        "image_urls": image_urls, 
                        "metadata": metadata,
                        "extracted_with": "manual_fallback"
                    }
            else:
                # Manual extraction only
                images = sb.execute_cdp_cmd("Runtime.evaluate", {
                    "expression": """
                        function getBestSrcFromSrcset(srcset) {
                            if (!srcset) return null;
                            
                            // Parse the srcset attribute
                            const srcsetParts = srcset.split(',').map(part => {
                                const [url, width] = part.trim().split(/\s+/);
                                // Extract numeric width (remove the 'w')
                                const numWidth = width ? parseInt(width.replace('w', '')) : 0;
                                return { url, width: numWidth };
                            });
                            
                            // Sort by width (descending) and return the largest image
                            srcsetParts.sort((a, b) => b.width - a.width);
                            return srcsetParts.length > 0 ? srcsetParts[0].url : null;
                        }
                        
                        Array.from(document.querySelectorAll('img'))
                            .filter(img => {
                                // Check if image is visible
                                const rect = img.getBoundingClientRect();
                                const style = window.getComputedStyle(img);
                                
                                // Minimum dimensions for non-icon/logo images (in pixels)
                                const MIN_WIDTH = 100;
                                const MIN_HEIGHT = 100;
                                const MIN_AREA = 10000; // width * height
                                
                                // Calculate actual dimensions
                                const area = rect.width * rect.height;
                                
                                return rect.width >= MIN_WIDTH && 
                                       rect.height >= MIN_HEIGHT && 
                                       area >= MIN_AREA &&
                                       style.display !== 'none' && 
                                       style.visibility !== 'hidden' &&
                                       parseFloat(style.opacity) > 0;
                            })
                            .flatMap(img => {
                                const urls = [];
                                
                                // Get the src attribute
                                if (img.src) {
                                    urls.push(img.src);
                                }
                                
                                // Get the best image from srcset if available
                                const srcset = img.getAttribute('srcset') || img.dataset.srcset;
                                if (srcset) {
                                    const bestSrc = getBestSrcFromSrcset(srcset);
                                    if (bestSrc) {
                                        urls.push(bestSrc);
                                    }
                                }
                                
                                return urls;
                            });
                    """,
                    "returnByValue": True,
                    "awaitPromise": True,
                })["result"]["value"]

                image_urls = clean_image_urls(images, url)
                metadata = extract_metadata(sb)
                
                response = {
                    "image_urls": image_urls, 
                    "metadata": metadata,
                    "extracted_with": "manual"
                }

        cache.set(cache_key, response)  # Cache the response

        return jsonify(response), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)
