import asyncio
import logging
import random
import re
import sys
from datetime import datetime
from bs4 import BeautifulSoup

async def send_message(message):
    print(message)

async def random_delay():
    delay = random.uniform(1, 5)  # Random delay between 1 and 5 seconds
    await asyncio.sleep(delay)

def read_html_file(file_name):
    with open(file_name, 'r', encoding='utf-8') as file:
        return file.read()

def process_listing(html_content, property_category_id):
    try:
        soup = BeautifulSoup(html_content, 'html.parser')

        # Create a dictionary containing the listing data
        listing_data = {}
        market_data = {}

        # Set listing type
        listing_data["property_category_id"] = property_category_id
        market_data["property_category_id"] = property_category_id

        # Extract the property ID (assumed to be part of the filename or url)
        property_id = "example_property_id"  # Modify this line to extract actual property ID if available
        listing_data["property_id"] = property_id

        # Title extraction logic
        title_element = soup.select_one('h2[data-testid="aviv.CDP.Sections.Description.MainDescription.Title"]')
        title = title_element.get_text(strip=True) if title_element else ""
        listing_data["title"] = title

        # Price extraction logic
        price_element = soup.select_one('span[data-testid="aviv.CDP.Sections.Hardfacts.Price.Value"]')
        price = price_element.get_text(strip=True) if price_element else ""
        price = re.sub("[^0-9]", "", price)  # Keep only numbers
        price = int(price) if price else 0
        listing_data["price"] = price

        # Image URLs extraction logic
        image_elements = soup.select('div[data-testid="aviv.CDP.Gallery.MobilePreview.ImageSlider"] img')
        image_urls = [img.get('src') for img in image_elements if img.get('src')]
        listing_data["image_urls"] = image_urls

        # Broker commission extraction logic
        commission_element = soup.select_one('div[data-testid="aviv.CDP.Sections.Price.MainPrice.commissionFee"]')
        broker_commission = commission_element is not None
        listing_data["broker_commission"] = broker_commission

        # Size extraction logic
        size_element = soup.select('div.css-j7qwjs span.css-2bd70b')[1]  # Assuming the second span is the size
        size = size_element.get_text(strip=True) if size_element else ""
        size = re.sub("[^0-9,]", "", size).replace(',', '.')  # Keep only numbers and convert comma to dot
        size = float(size) if size else 0
        listing_data["size"] = size

        # Rooms extraction logic
        rooms_element = soup.select('div.css-j7qwjs span.css-2bd70b')[0]  # Assuming the first span is the rooms
        rooms = rooms_element.get_text(strip=True) if rooms_element else ""
        rooms = re.sub("[^0-9,]", "", rooms).replace(',', '.')  # Keep only numbers and convert comma to dot
        rooms = float(rooms) if rooms else 0
        listing_data["rooms"] = rooms

        # Foreclosure extraction logic
        foreclosure_element = soup.select_one('li[data-testid="aviv.CDP.Header-NavigationBar-NavigationBarL1EntryExpandable[0]"]')
        foreclosure_text = foreclosure_element.get_text(strip=True) if foreclosure_element else ""
        foreclosure = "zwangsversteigerung" in foreclosure_text.lower()
        listing_data["foreclosure"] = foreclosure

        # Description extraction logic
        description_element = soup.select_one('div[data-testid="aviv.CDP.Sections.Description.AdditionalDescription.GradientTextBox-content"]')
        description_html = description_element.decode_contents() if description_element else ""
        description_html = re.sub("<.*?>", "", description_html)  # Remove HTML tags
        listing_data["description"] = description_html.strip()

        # Street extraction logic
        street_element = soup.select_one('div[data-testid="aviv.CDP.Sections.Location.Address"] span.css-62z2dn')
        street = street_element.get_text(strip=True) if street_element else ""
        listing_data["street"] = street.strip()

        print("Platform ID: 2")
        listing_data["platform_id"] = 2  # 1 = Kleinanzeigen, 2 = Immowelt, 3 = Immoscout

        print("Listing is active")
        listing_data["active"] = True

        listed_at = datetime.now().strftime("%Y-%m-%d")
        print("Listed at:", listed_at)
        listing_data["listed_at"] = listed_at

        print("=" * 100)
        print("DONE")
        print("=" * 100)

        return listing_data

    except Exception as e:
        print("Error in process_listing:", str(e))
        return None

async def main():
    try:
        print("=" * 100)
        print("Starting main loop...")
        print("=" * 100)
        
        file_names = [
            "Wohnung zum Kauf.html",
            "Wohnung zum Kauf2.html",
            "Wohnung zum Kauf3.html",
            "Wohnung zum Kauf4.html",
            "Wohnung zum Kauf6.html"
        ]

        for file_name in file_names:
            print(f"Processing file: {file_name}")
            html_content = read_html_file(file_name)
            listing_data = process_listing(html_content, 1)
            print(listing_data)
            await random_delay()  # Introduce a random delay after each request

    except Exception as e:
        print("Error in main loop:", str(e))
        await send_message(f"🔴 IWS APARTMENTS - Error in main loop: {str(e)}")

    finally:
        await send_message(f"✅ IWS APARTMENTS - stopped")

if __name__ == "__main__":
    asyncio.run(main())
    sys.exit()  # This will cause the container to stop after the script is done
