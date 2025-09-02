# Colab

### image download

import requests
from bs4 import BeautifulSoup
import os
import logging
import time
from urllib.parse import urlsplit, urlparse
from tqdm import tqdm
from collections import defaultdict

# --- Configuration ---
# Folder where you want to save the images
DOWNLOAD_FOLDER = "midjourney_images"
# Base URL of the website
BASE_URL = "https://midjourneysref.com"

# Set up comprehensive logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('scraper.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Statistics tracking
stats = {
    'pages_attempted': 0,
    'pages_successful': 0,
    'images_found': 0,
    'images_downloaded': 0,
    'images_skipped': 0,
    'images_failed': 0,
    'errors': defaultdict(int)
}

def validate_url(url):
    """Validates if a URL is properly formed."""
    try:
        result = urlparse(url)
        return all([result.scheme, result.netloc])
    except Exception:
        return False

def test_connectivity():
    """Tests basic connectivity to the target website."""
    logger.info("Testing connectivity to the target website...")
    try:
        response = requests.get(BASE_URL, timeout=10)
        if response.status_code == 200:
            logger.info(f"✓ Successfully connected to {BASE_URL}")
            return True
        else:
            logger.error(f"✗ Website returned status code {response.status_code}")
            return False
    except requests.exceptions.ConnectionError:
        logger.error(f"✗ Cannot connect to {BASE_URL}. Check your internet connection.")
        return False
    except requests.exceptions.Timeout:
        logger.error(f"✗ Connection to {BASE_URL} timed out.")
        return False
    except Exception as e:
        logger.error(f"✗ Unexpected error testing connectivity: {e}")
        return False

def create_download_folder():
    """Creates the download folder if it doesn't already exist."""
    try:
        if not os.path.exists(DOWNLOAD_FOLDER):
            logger.info(f"Creating directory: {DOWNLOAD_FOLDER}")
            os.makedirs(DOWNLOAD_FOLDER)
            logger.info(f"✓ Successfully created directory: {DOWNLOAD_FOLDER}")
        else:
            logger.info(f"✓ Directory already exists: {DOWNLOAD_FOLDER}")
        
        # Test write permissions
        test_file = os.path.join(DOWNLOAD_FOLDER, '.test_write_permission')
        try:
            with open(test_file, 'w') as f:
                f.write('test')
            os.remove(test_file)
            logger.info("✓ Write permissions confirmed for download folder")
        except Exception as e:
            logger.error(f"✗ No write permission for {DOWNLOAD_FOLDER}: {e}")
            raise
            
    except Exception as e:
        logger.error(f"✗ Failed to create or access download folder: {e}")
        raise

def download_image(url, folder):
    """Downloads a single image from a URL into a specified folder."""
    try:
        # Validate URL format
        if not validate_url(url):
            logger.warning(f"Invalid URL format: {url}")
            stats['images_failed'] += 1
            stats['errors']['invalid_url'] += 1
            return False

        logger.debug(f"Attempting to download: {url}")
        
        # Get the image content with detailed error handling
        try:
            response = requests.get(url, stream=True, timeout=15)
            response.raise_for_status()
        except requests.exceptions.Timeout:
            logger.warning(f"Timeout downloading {url}")
            stats['images_failed'] += 1
            stats['errors']['timeout'] += 1
            return False
        except requests.exceptions.ConnectionError:
            logger.warning(f"Connection error downloading {url}")
            stats['images_failed'] += 1
            stats['errors']['connection_error'] += 1
            return False
        except requests.exceptions.HTTPError as e:
            logger.warning(f"HTTP error {e.response.status_code} downloading {url}")
            stats['images_failed'] += 1
            stats['errors'][f'http_{e.response.status_code}'] += 1
            return False

        # Validate content type
        content_type = response.headers.get('content-type', '').lower()
        if not any(img_type in content_type for img_type in ['image/', 'jpeg', 'jpg', 'png', 'webp']):
            logger.warning(f"Invalid content type '{content_type}' for {url}")
            stats['images_failed'] += 1
            stats['errors']['invalid_content_type'] += 1
            return False

        # Create filename with better validation
        filename = os.path.basename(urlsplit(url).path)
        if not filename or len(filename) < 1:
            # Generate filename from URL hash if basename is empty
            filename = f"image_{hash(url) % 100000}"
            logger.debug(f"Generated filename for URL without clear filename: {filename}")
        
        # Add extension if missing
        if not os.path.splitext(filename)[1]:
            # Try to determine extension from content-type
            if 'jpeg' in content_type or 'jpg' in content_type:
                filename += '.jpg'
            elif 'png' in content_type:
                filename += '.png'
            elif 'webp' in content_type:
                filename += '.webp'
            else:
                filename += '.jpg'  # default
            
        filepath = os.path.join(folder, filename)

        # Check if file already exists
        if os.path.exists(filepath):
            file_size = os.path.getsize(filepath)
            if file_size > 0:
                logger.debug(f"Skipping {filename}, already exists ({file_size} bytes)")
                stats['images_skipped'] += 1
                return True
            else:
                logger.warning(f"Found empty file {filename}, re-downloading")
                os.remove(filepath)

        # Validate response size
        content_length = response.headers.get('content-length')
        if content_length:
            size_mb = int(content_length) / (1024 * 1024)
            if size_mb > 50:  # Arbitrary large file check
                logger.warning(f"Large file detected ({size_mb:.1f}MB): {url}")
            elif size_mb < 0.001:  # Very small file check
                logger.warning(f"Suspiciously small file ({int(content_length)} bytes): {url}")

        # Save the image to a file
        bytes_written = 0
        with open(filepath, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:  # filter out keep-alive chunks
                    f.write(chunk)
                    bytes_written += len(chunk)

        # Validate downloaded file
        if bytes_written == 0:
            logger.error(f"Downloaded file is empty: {filename}")
            os.remove(filepath)
            stats['images_failed'] += 1
            stats['errors']['empty_file'] += 1
            return False
        
        final_size = os.path.getsize(filepath)
        logger.debug(f"✓ Successfully downloaded {filename} ({final_size} bytes)")
        stats['images_downloaded'] += 1
        return True

    except Exception as e:
        logger.error(f"Unexpected error downloading {url}: {e}")
        stats['images_failed'] += 1
        stats['errors']['unexpected_download_error'] += 1
        return False

def scrape_page(page_number):
    """Scrapes a single page to find and download all images."""
    stats['pages_attempted'] += 1
    target_url = f"{BASE_URL}/discover?page={page_number}"
    logger.info(f"\n--- Scraping Page {page_number}: {target_url} ---")

    try:
        # Get the HTML content with retries
        max_retries = 3
        for attempt in range(max_retries):
            try:
                logger.debug(f"Fetching page content (attempt {attempt + 1}/{max_retries})")
                response = requests.get(target_url, timeout=10)
                response.raise_for_status()
                break
            except requests.exceptions.RequestException as e:
                logger.warning(f"Attempt {attempt + 1} failed: {e}")
                if attempt == max_retries - 1:
                    raise
                time.sleep(2)  # Wait before retry

        # Validate response
        if len(response.text) < 1000:
            logger.warning(f"Page content seems unusually short ({len(response.text)} characters)")
        
        logger.debug(f"Received {len(response.text)} characters of HTML content")
        
        soup = BeautifulSoup(response.text, 'html.parser')

        # Validate HTML structure
        if not soup.find('html'):
            logger.error("Invalid HTML structure received - no <html> tag found")
            stats['errors']['invalid_html'] += 1
            return

        # Find thumbnail images with detailed feedback
        logger.debug("Searching for image thumbnails using selector: 'div.m-5 img.cursor-pointer'")
        thumbnail_tags = soup.select('div.m-5 img.cursor-pointer')
        
        if not thumbnail_tags:
            logger.warning("No images found with primary selector. Trying alternative selectors...")
            
            # Try alternative selectors
            alternative_selectors = [
                'img.cursor-pointer',
                'div.m-5 img',
                'img[src*="midjourney"]',
                'img[src*="cdn"]'
            ]
            
            for selector in alternative_selectors:
                logger.debug(f"Trying selector: {selector}")
                thumbnail_tags = soup.select(selector)
                if thumbnail_tags:
                    logger.info(f"Found {len(thumbnail_tags)} images with alternative selector: {selector}")
                    break
            
            if not thumbnail_tags:
                logger.error("No images found with any selector. The site structure may have changed.")
                logger.debug("Available img tags on page:")
                all_imgs = soup.find_all('img')
                for i, img in enumerate(all_imgs[:5]):  # Show first 5 img tags
                    logger.debug(f"  {i+1}. {img}")
                if len(all_imgs) > 5:
                    logger.debug(f"  ... and {len(all_imgs) - 5} more img tags")
                stats['errors']['no_images_found'] += 1
                return

        logger.info(f"✓ Found {len(thumbnail_tags)} images to download on page {page_number}")
        stats['images_found'] += len(thumbnail_tags)
        
        # Download images with progress tracking
        successful_downloads = 0
        failed_downloads = 0
        
        for i, img_tag in enumerate(tqdm(thumbnail_tags, desc=f"Page {page_number}")):
            logger.debug(f"Processing image {i+1}/{len(thumbnail_tags)}")
            
            thumbnail_src = img_tag.get('src')
            if not thumbnail_src:
                logger.warning(f"Image tag {i+1} has no 'src' attribute: {img_tag}")
                failed_downloads += 1
                continue

            logger.debug(f"Thumbnail src: {thumbnail_src}")

            # Extract the full-resolution URL
            try:
                if 'fit=cover/' in thumbnail_src:
                    full_res_url = thumbnail_src.split('fit=cover/')[1]
                    logger.debug(f"Extracted full-res URL: {full_res_url}")
                else:
                    # Try using the thumbnail URL directly
                    full_res_url = thumbnail_src
                    logger.debug(f"Using thumbnail URL directly: {full_res_url}")
                
                # Download the image
                if download_image(full_res_url, DOWNLOAD_FOLDER):
                    successful_downloads += 1
                else:
                    failed_downloads += 1
                    
            except Exception as e:
                logger.error(f"Error processing image {i+1}: {e}")
                failed_downloads += 1
                stats['errors']['processing_error'] += 1

        logger.info(f"Page {page_number} complete: {successful_downloads} successful, {failed_downloads} failed")
        stats['pages_successful'] += 1

    except requests.exceptions.RequestException as e:
        logger.error(f"✗ Failed to fetch page {page_number}. Error: {e}")
        stats['errors']['page_fetch_error'] += 1
    except Exception as e:
        logger.error(f"✗ Unexpected error processing page {page_number}: {e}")
        stats['errors']['unexpected_page_error'] += 1

def print_summary():
    """Prints a detailed summary of the scraping session."""
    logger.info("\n" + "="*60)
    logger.info("SCRAPING SESSION SUMMARY")
    logger.info("="*60)
    logger.info(f"Pages attempted: {stats['pages_attempted']}")
    logger.info(f"Pages successful: {stats['pages_successful']}")
    logger.info(f"Images found: {stats['images_found']}")
    logger.info(f"Images downloaded: {stats['images_downloaded']}")
    logger.info(f"Images skipped (already exist): {stats['images_skipped']}")
    logger.info(f"Images failed: {stats['images_failed']}")
    
    if stats['errors']:
        logger.info("\nError breakdown:")
        for error_type, count in stats['errors'].items():
            logger.info(f"  {error_type}: {count}")
    
    success_rate = (stats['images_downloaded'] / max(stats['images_found'], 1)) * 100
    logger.info(f"\nOverall success rate: {success_rate:.1f}%")
    
    if stats['images_downloaded'] > 0:
        logger.info(f"✓ Images saved in: {os.path.abspath(DOWNLOAD_FOLDER)}")
    
    # Provide troubleshooting suggestions
    if stats['images_failed'] > 0:
        logger.info("\nTroubleshooting suggestions:")
        if stats['errors']['timeout'] > 0:
            logger.info("- Many timeouts occurred. Check your internet connection speed.")
        if stats['errors']['connection_error'] > 0:
            logger.info("- Connection errors occurred. Check your internet connectivity.")
        if stats['errors']['no_images_found'] > 0:
            logger.info("- No images found. The website structure may have changed.")
        if stats['errors']['invalid_url'] > 0:
            logger.info("- Invalid URLs found. The site may have changed its URL structure.")


logger.info("Starting Midjourney image scraper with enhanced feedback")
    
try:
    # Test connectivity first
    if not test_connectivity():
        logger.error("Cannot proceed without connectivity. Exiting.")
        exit(1)
        
    # Create the folder to store images
    create_download_folder()

    # Configuration validation
    start_page = 0
    end_page = 50
        
    if start_page > end_page:
        logger.error(f"Invalid page range: start_page ({start_page}) > end_page ({end_page})")
        exit(1)
        
    logger.info(f"Configured to scrape pages {start_page} to {end_page}")
    total_pages = end_page - start_page + 1
    logger.info(f"Will attempt to scrape {total_pages} pages")

    # Scrape pages
    for page in range(start_page, end_page + 1):
        scrape_page(page)
            
        # Add small delay between pages to be respectful
        if page < end_page:
            time.sleep(1)

    # Print comprehensive summary
    print_summary()

except KeyboardInterrupt:
    logger.info("\nScraping interrupted by user")
    print_summary()
except Exception as e:
    logger.error(f"Fatal error: {e}")
    print_summary()
    raise


#### dataset construction

def get_almost_sref(x):
    x = x.split("--sref")[-1]
    return Path(x).stem.split('-')[0] if '-' in Path(x).stem else Path(x).stem

def get_first_all_numbers(x):
    #print("x :", x)
    l = x.strip().split("_")
    req = x
    #print("l :", l)
    for ele in l:
        if ele.strip() and all(map(lambda y: y in "0123456789", ele)):
            #print("ele :" ,ele)
            return ele
    return req

import pathlib 
import pandas as pd 
import os
from pathlib import Path
from datasets import Dataset, Image as HfImage
df = pd.DataFrame( 
pd.Series(
    pathlib.Path("midjourney_images").rglob("*")
).map(str)
)
df.columns = ["image"]
df["filename"] = df["image"].map(lambda x: x.split("/")[-1])
df["sref"] = df["image"].map(get_almost_sref)
df["sref"] = df["sref"].map(get_first_all_numbers) 
df = df[
    df["sref"].map(
        lambda x: bool(x.strip()) and all(map(lambda y: y in "0123456789", x.strip()))
    )
].reset_index().iloc[:, 1:]

ds = Dataset.from_pandas(df.sort_values("sref").reset_index().iloc[:, 1:]).cast_column("image", HfImage())
ds

!huggingface-cli login 

ds.push_to_hub("svjack/midjourney_images_{}".format(len(df)))
