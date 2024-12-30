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
    """Extract metadata such as og:title, og:description, etc."""
    metadata = {}
    meta_elements = sb.cdp.find_elements("meta[property^='og:'], meta[name]")

    for meta in meta_elements:
        property_attr = meta.get_attribute("property")
        name_attr = meta.get_attribute("name")
        content_attr = meta.get_attribute("content")

        # Look for `og:*` or other meta tags
        if property_attr:
            metadata[property_attr] = content_attr
        elif name_attr:
            metadata[name_attr] = content_attr

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
                'Network.setBlockedURLs', {"urls": [
                    "*.js",
                    "*.css",
                    "*.png",
                    "*.jpg",
                    "*.jpeg",
                    "*.gif",
                    "*.svg",
                    "*.woff",
                    "*.woff2",
                    "*.ttf",
                    "*.eot",
                    "*.ico",
                    "*.mp4",
                    "*.webm",
                    "*.ogg",
                    "*.mp3",
                    "*.wav",
                ]})
            sb.execute_cdp_cmd('Network.enable', {})

            sb.wait_for_ready_state_complete(timeout=30)

            # Extract image URLs
            items = sb.cdp.find_elements("img")
            image_urls = [item.get_attribute("src") for item in items]
            image_urls = clean_image_urls(image_urls)  # Remove duplicates and non-HTTPS URLs

            # Extract metadata
            metadata = extract_metadata(sb)

        response = {"image_urls": image_urls, "metadata": metadata}
        cache.set(cache_key, response)  # Cache the response

        return jsonify(response), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)
