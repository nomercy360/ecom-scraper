from flask import Flask, request, jsonify
from seleniumbase import SB
from flask_cors import CORS

app = Flask(__name__)
CORS(app)  # Allow all CORS requests for now


def extract_metadata(sb):
    """Extract metadata such as og:title, og:description, etc."""
    metadata = {}
    meta_elements = sb.cdp.find_elements("meta")

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

    try:
        with SB(uc=True, test=True, locale_code="en", pls="none", headless=True) as sb:
            sb.activate_cdp_mode(url)
            sb.sleep(3)  # Allow the page to load

            # Extract image URLs
            items = sb.cdp.find_elements("img")
            image_urls = [item.get_attribute("src") for item in items]
            image_urls = clean_image_urls(image_urls)  # Remove duplicates and non-HTTPS URLs

            # Extract metadata
            metadata = extract_metadata(sb)

        return jsonify({"image_urls": image_urls, "metadata": metadata}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)