from flask import Flask, request, jsonify
from seleniumbase import SB

app = Flask(__name__)


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

            # Extract metadata
            metadata = extract_metadata(sb)

        return jsonify({"image_urls": image_urls, "metadata": metadata}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)
