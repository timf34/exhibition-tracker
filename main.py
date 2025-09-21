#!/usr/bin/env python3
"""
Simple Beautiful Soup script to fetch and print raw HTML content from National Gallery of Ireland exhibitions page.
"""

import requests
from bs4 import BeautifulSoup


def main():
    """Fetch the page and print the raw Beautiful Soup content."""
    url = "https://www.famsf.org/whats-on"
    
    print(f"Fetching content from: {url}")
    print("=" * 80)
    
    try:
        # Set up headers to mimic a real browser
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        
        # Fetch the page
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        
        # Create Beautiful Soup object
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Clean and reduce HTML for exhibition content
        print("Cleaning and reducing HTML for exhibition content...")
        
        # Remove all <style> tags
        for style_tag in soup.find_all('style'):
            style_tag.decompose()
        
        # Remove all <script> tags
        for script_tag in soup.find_all('script'):
            script_tag.decompose()
        
        # Remove all <noscript> tags
        for noscript_tag in soup.find_all('noscript'):
            noscript_tag.decompose()
        
        # Remove all <path> tags (SVG paths)
        for path_tag in soup.find_all('path'):
            path_tag.decompose()
        
        # Remove all empty <svg> tags
        for svg_tag in soup.find_all('svg'):
            if not svg_tag.get_text(strip=True):
                svg_tag.decompose()
        
        # Remove excessive meta tags (keep only essential ones)
        essential_meta = ['charset', 'viewport', 'og:title', 'twitter:title']
        for meta_tag in soup.find_all('meta'):
            if not any(attr in str(meta_tag) for attr in essential_meta):
                meta_tag.decompose()
        
        # Remove all link tags (CSS, icons, etc.)
        for link_tag in soup.find_all('link'):
            link_tag.decompose()
        
        # Remove excessive attributes from all tags
        for tag in soup.find_all():
            # Keep only essential attributes
            essential_attrs = ['href', 'src', 'alt', 'title', 'id']
            attrs_to_remove = []
            for attr in tag.attrs:
                if attr not in essential_attrs:
                    attrs_to_remove.append(attr)
            for attr in attrs_to_remove:
                del tag[attr]
        
        # Remove placeholder images and data URLs
        for img_tag in soup.find_all('img'):
            src = img_tag.get('src', '')
            if 'data:image' in src or 'placeholder' in src:
                img_tag.decompose()
        
        # Remove picture tags and keep only main img
        for picture_tag in soup.find_all('picture'):
            main_img = picture_tag.find('img', {'data-main-image': True})
            if main_img:
                # Replace picture with just the main image
                picture_tag.replace_with(main_img)
            else:
                picture_tag.decompose()
        
        # Remove source tags (from picture elements)
        for source_tag in soup.find_all('source'):
            source_tag.decompose()
        
        # Remove video tags (likely promotional content)
        for video_tag in soup.find_all('video'):
            video_tag.decompose()
        
        # Simplify navigation - keep only exhibition-related links
        for nav_tag in soup.find_all('nav'):
            # Keep nav if it contains exhibition-related content
            nav_text = nav_tag.get_text().lower()
            if not any(keyword in nav_text for keyword in ['exhibition', 'event', 'show', 'gallery']):
                nav_tag.decompose()
        
        # Print some basic info
        print(f"Status Code: {response.status_code}")
        print(f"Content Length: {len(response.content)} bytes")
        print(f"Page Title: {soup.title.string if soup.title else 'No title found'}")
        print("=" * 80)
        print()
        
        # Save the cleaned Beautiful Soup content to a file
        output_file = "cleaned_soup.html"
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(soup.prettify())
        
        print(f"Cleaned Beautiful Soup content saved to: {output_file}")
        print(f"File size: {len(soup.prettify())} characters")
        
    except requests.RequestException as e:
        print(f"Error fetching the page: {e}")
    except Exception as e:
        print(f"Error parsing the content: {e}")


if __name__ == "__main__":
    main()
