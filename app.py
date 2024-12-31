from flask import Flask, request, jsonify
from seleniumbase import SB
from flask_cors import CORS
from flask_caching import Cache

app = Flask(__name__)
CORS(app)  # Allow all CORS requests for now

app.config['CACHE_TYPE'] = 'SimpleCache'
app.config['CACHE_DEFAULT_TIMEOUT'] = 300  # Cache timeout in seconds
cache = Cache(app)


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


def clean_image_urls(image_urls):
    """Remove duplicates and filter out non-HTTPS URLs."""
    cleaned_urls = {url for url in image_urls if url and url.startswith("https://")}
    return list(cleaned_urls)


@app.route('/extract-content', methods=['POST'])
def extract_content():
    data = request.json
    url = data.get("url")

    if not url:
        return jsonify({"error": "URL is required"}), 400

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
                {"urls": ["*.png", "*.jpg", "*.jpeg", "*.svg", "*.gif", "*.css", "*.woff2", "*.webp"]})
            sb.execute_cdp_cmd('Network.enable', {})

            sb.wait_for_ready_state_complete(timeout=10)

            # Extract image URLs
            images = sb.execute_cdp_cmd("Runtime.evaluate", {
                "expression": """
                    Array.from(document.querySelectorAll('img'))
                        .map(img => img.src)
                        .filter(src => src.startsWith('https://'));
                """,
                "returnByValue": True
            })["result"]["value"]

            image_urls = clean_image_urls(images)

            # Extract metadata
            metadata = extract_metadata(sb)

        response = {"image_urls": image_urls, "metadata": metadata}
        cache.set(cache_key, response)  # Cache the response

        return jsonify(response), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)
