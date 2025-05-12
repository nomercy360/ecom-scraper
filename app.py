from flask import Flask, request, jsonify
from seleniumbase import SB
from flask_cors import CORS
from flask_caching import Cache

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


@app.route('/extract-content', methods=['POST'])
def extract_content():
    data = request.json
    url = data.get("url")

    if not url:
        return jsonify({"error": "URL is required"}), 400

    url = clean_url(url)

    if not is_valid_url(url):
        return jsonify({"error": "Invalid URL format. URL must start with http:// or https://"}), 400

    # Check cache for existing response
    cache_key = f"content_{url}"
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

            # Extract only visible and sufficiently large image URLs, including srcset
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

            # Extract metadata
            metadata = extract_metadata(sb)

        response = {"image_urls": image_urls, "metadata": metadata}
        cache.set(cache_key, response)  # Cache the response

        return jsonify(response), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)
