import asyncio
import logging
from pyppeteer import launch
import pyppeteer.errors
import random
import re
import sys
import requests
from datetime import datetime
import supabase
from supabase import create_client, Client
from urllib.parse import urlparse

############################################################################################################
############################################## CONFIGURATION ###############################################
############################################################################################################

local_test = True  # Set to False when running on Azure
pages_to_scrape = 1  # Set to 30 when running on Azure

# Set the logging level of pyppeteer to WARNING
logging.getLogger('pyppeteer').setLevel(logging.WARNING)

user_agents = [
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_8_2) AppleWebKit/537.17 (KHTML, like Gecko) Chrome/24.0.1309.0 Safari/537.17',
    'Mozilla/5.0 (compatible; MSIE 10.6; Windows NT 6.1; Trident/5.0; InfoPath.2; SLCC1; .NET CLR 3.0.4506.2152; .NET CLR 3.5.30729; .NET CLR 2.0.50727) 3gpp-gba UNTRUSTED/1.0',
    'Opera/12.80 (Windows NT 5.1; U; en) Presto/2.10.289 Version/12.02',
    'Mozilla/4.0 (compatible; MSIE 5.5; Windows NT)',
    'Mozilla/3.0',
    'Mozilla/5.0 (iPhone; U; CPU like Mac OS X; en) AppleWebKit/420+ (KHTML, like Gecko) Version/3.0 Mobile/1A543a Safari/419.3',
    'Mozilla/5.0 (Linux; U; Android 0.5; en-us) AppleWebKit/522+ (KHTML, like Gecko) Safari/419.3',
    'Opera/9.00 (Windows NT 5.1; U; en)'
]

api_url = ''  # TODO Must be changed each time the API gets redeployed
api_headers = {}

############################################################################################################
############################################################################################################
############################################################################################################

async def send_message(message):
    print(message)

async def random_delay():
    delay = random.uniform(1, 5)  # Random delay between 1 and 5 seconds
    await asyncio.sleep(delay)

async def open_browser():
    browser = None  # Initialize browser to None
    try:
        user_agent = random.choice(user_agents)
        if local_test:
            browser = await launch(
                headless=False,
                slowMo=10,
                executablePath='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',  # Ensure the correct path
                args=['--no-sandbox', '--disable-setuid-sandbox'],
                userAgent=user_agent
            )
        else:
            browser = await launch(
                headless=False,
                executablePath='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',  # Ensure the correct path
                autoClose=False,
                slowMo=10,
                args=['--no-sandbox', '--disable-setuid-sandbox'],
                userAgent=user_agent
            )
    except Exception as e:
        print(e)
        await send_message(f"🔴 IWS - Error: {e}")
        if browser:
            await browser.close()
    return browser

def check_api_value(data, key, default_value, target_type):
    value = data.get(key, default_value)
    if value is not None:
        try:
            return target_type(value)
        except (ValueError, TypeError):
            return default_value
    return default_value

async def process_listing(url, property_category_id):
    browser = None  # Initialize browser to None
    try:
        browser = await open_browser()
        page = await browser.newPage()
        print("Opening listing:", url)
        await page.goto(url, {'timeout': 120000})

        print("=" * 100)
        print("Processing listing...")
        print("=" * 100)
        
        # Create a dictionary containing the listing data
        listing_data = {}
        market_data = {}

        # Set listing type
        print("Property Category:", property_category_id)
        listing_data["property_category_id"] = property_category_id
        market_data["property_category_id"] = property_category_id

        # Extract the property ID from the url (https://www.immowelt.de/expose/2btm45q) and print it
        property_id = url.split("/")[-1]
        print("Property ID:", property_id)
        listing_data["property_id"] = property_id

        # Updated Title extraction logic
        title_element = await page.querySelector("h1")
        if not title_element:
            title_element = await page.querySelector("title")
        title = await (await title_element.getProperty("textContent")).jsonValue() if title_element else ""
        listing_data["title"] = title.strip()
        print("Title:", title.strip())

        price_element = await page.querySelector("div.has-font-300 strong.ng-star-inserted")
        price = await (await price_element.getProperty("textContent")).jsonValue() if price_element else ""
        if price.strip() == "VB":
            price = "0"
        else:
            price = re.sub("[^0-9]", "", price.strip())  # Remove all non-numeric characters
            price = int(price) if price else 0
        print("Price:", price)

        # Evaluate JavaScript on the page to extract image URLs
        image_urls = await page.evaluate('''() => {
            const pictureElements = document.querySelectorAll("div.swiper-slide img.swiper-lazy");
            const urls = [];

            for (const picture of pictureElements) {
                const imageUrl = picture.getAttribute("src");
                if (imageUrl) {
                    urls.push(imageUrl);
                }
            }

            return urls;
        }''')
        print("Image URLs:", image_urls)
        listing_data["image_urls"] = image_urls

        commission_element = await page.querySelector('div[data-cy="commission"] p.card-content')
        commission_text = await (await commission_element.getProperty("textContent")).jsonValue() if commission_element else ""
        if "provisionsfrei" in commission_text.lower():
            print("Broker commission: False")
            listing_data["broker_commission"] = False
        else:
            print("Broker commission: True")
            listing_data["broker_commission"] = True

        size_element = await page.querySelector("div.hardfact span.has-font-300")
        size = await (await size_element.getProperty("textContent")).jsonValue() if size_element else ""
        size = re.sub(" m²", "", size)
        size = size.replace(",", ".")
        print("Wohnfläche:", size.strip())
        try:
            listing_data["size"] = float(size.strip()) if size.strip() else 0
        except:
            listing_data["size"] = size.strip()

        rooms_elements = await page.querySelectorAll("div.hardfact span.has-font-300")
        rooms_element = rooms_elements[1] if len(rooms_elements) > 1 else None
        rooms = await (await rooms_element.getProperty("textContent")).jsonValue() if rooms_element else ""
        # check if the text contains the word "k.A."
        if "k.A." in rooms.strip():
            print("Zimmer: 0")
            listing_data["rooms"] = 0
        else:
            rooms = rooms.replace(",", ".")
            print("Zimmer:", rooms.strip())
            listing_data["rooms"] = float(rooms.strip()) if rooms.strip() else 0

        foreclosure_element = await page.querySelector("div.flex.flex-wrap sd-badge.badge--primary")
        foreclosure_text = await (await foreclosure_element.getProperty("textContent")).jsonValue() if foreclosure_element else ""
        if "Zwangsversteigerung" in foreclosure_text:
            print("Foreclosure: True")
            listing_data["foreclosure"] = True
        else:
            print("Foreclosure: False")
            listing_data["foreclosure"] = False

        row2_element = await page.querySelector("div[data-test='additional-costs']")
        row2_text = await (await row2_element.getProperty("textContent")).jsonValue() if row2_element else ""
        if "Hausgeld" in row2_text:
            hausgeld_element = await page.querySelector("div[data-test='additional-costs']")
            hausgeld = await (await hausgeld_element.getProperty("textContent")).jsonValue() if hausgeld_element else ""
            hausgeld = re.sub("[^0-9]", "", hausgeld.strip())
            print("Hausgeld:", hausgeld.strip())
            listing_data["household_costs"] = int(hausgeld) if hausgeld else 0

        category_element_1 = await page.querySelector("div[data-test='feature-categories']")
        category_text_1 = await (await category_element_1.getProperty("textContent")).jsonValue() if category_element_1 else ""

        category_element_2 = await page.querySelector("div[data-test='feature-categories']")
        category_text_2 = await (await category_element_2.getProperty("textContent")).jsonValue() if category_element_2 else ""

        if "Kategorie" in category_text_1.strip():  # Category is always on in first column
            category_text_1 = re.sub("Kategorie", "", category_text_1.strip())
            print("Property Type: ", category_text_1.strip())
            listing_data["property_type"] = category_text_1.strip()
        else:
            print("Property Type: Andere Wohnungstypen")
            listing_data["property_type"] = "Andere Wohnungstypen"

        try:
            if "Wohnungslage" in category_text_1.strip():
                if "Erdgeschoss" in category_text_1.strip():
                    print("Floor: ", 0)
                    listing_data["floor"] = 0
                elif "Dachgeschoss" in category_text_1.strip():
                    print("Floor: ", 0)
                    listing_data["floor"] = 0
                else:
                    category_text_1 = re.sub("[^0-9]", "", category_text_1.strip())
                    print("Floor: ", category_text_1.strip())
                    listing_data["floor"] = int(category_text_1.strip()) if category_text_1 else 0
            elif "Wohnungslage" in category_text_2.strip():
                category_text_2 = re.sub("[^0-9]", "", category_text_2.strip())
                print("Floor: ", category_text_2.strip())
                listing_data["floor"] = int(category_text_2.strip())
        except:
            print("Floor: ", 0)
            listing_data["floor"] = 0

        if "Bezug" in category_text_1.strip():
            category_text_1 = category_text_1.replace("Bezug", "")
            print("Available from: ", category_text_1.strip())
            listing_data["available_from"] = category_text_1.strip()
        elif "Bezug" in category_text_2.strip():
            category_text_2 = category_text_2.replace("Bezug", "")
            print("Available from: ", category_text_2.strip())
            listing_data["available_from"] = category_text_2.strip()

        
        try:
            year_built = ""
            elements_containing_baujahr = await page.querySelectorAll('*:not(script):not(style):not(noscript)')

            for element in elements_containing_baujahr:
                text = await (await element.getProperty('textContent')).jsonValue()
                match = re.search(r'Baujahr\s*:\s*(\d{4})', text)
                if match:
                    year_built = match.group(1)
                    break

            if year_built.isdigit():
                listing_data["year_built"] = int(year_built)
                print("Year of construction:", year_built)
            else:
                listing_data["year_built"] = ""
                print("Year of construction: Not found")
        except Exception as e:
            print("Error extracting year of construction:", e)
            listing_data["year_built"] = ""
        # listing_data["year_built"] = int(year_built) if year_built.isdigit() else ""

        try:
            features_element = await page.querySelector("div[data-test='features']")
            features_elements = await features_element.querySelectorAll("li")
            features = []
            for feature_element in features_elements:
                feature_text = await (await feature_element.getProperty("textContent")).jsonValue() if feature_element else ""
                features.append(feature_text.strip())
            print("Features:", features)
            listing_data["features"] = features
        except:
            print("Features: None")
            listing_data["features"] = []

        try:
            # Click the "Mehr anzeigen" button to expand the content
            await page.waitForSelector("app-details sd-read-more[morelabel='Mehr anzeigen'].ng-star-inserted > a", timeout=50000)
            await page.evaluate('''() => {
                const readMoreButtons = document.querySelectorAll('app-details sd-read-more[morelabel="Mehr anzeigen"].ng-star-inserted > a');
                readMoreButtons.forEach(button => button.click());
            }''')

            description_elements = await page.querySelectorAll('div.card-content')
            description_html = ""
            for description_element in description_elements:
                html_content = await (await description_element.getProperty("innerHTML")).jsonValue() if description_element else ""
                description_html += html_content

            description_html = re.sub("<div.*?>", "", description_html.strip())
            description_html = re.sub("</div>", "", description_html.strip())
            description_html = re.sub("<script.*?>.*?</script>", "", description_html.strip())
            description_html = re.sub(r'<style>.*?</style>', '', description_html, flags=re.DOTALL)
            description_html = re.sub("<br>", "\n", description_html)
            description_html = re.sub("<p>", "\n", description_html)
            description_html = re.sub("</p>", "", description_html)
            description_html = re.sub("<h1>", "\n", description_html)
            description_html = re.sub("</h1>", "", description_html)
            description_html = re.sub("<h2>", "\n", description_html)
            description_html = re.sub("</h2>", "", description_html)
            description_html = re.sub("<h3>", "\n", description_html)
            description_html = re.sub("</h3>", "", description_html)
            description_html = re.sub("<ul>", "\n", description_html)
            description_html = re.sub("</ul>", "", description_html)
            description_html = re.sub("<li>", "\n", description_html)
            description_html = re.sub("</li>", "", description_html)
            description_html = re.sub("<strong>", "", description_html)
            description_html = re.sub("</strong>", "", description_html)
            description_html = re.sub("<.*?>", "", description_html)
            description_html = re.sub("sdlink=\".*?\"", "", description_html)
            description_html = re.sub("<a.*?>(.*?)</a>", "", description_html)
            description_html = re.sub("Weniger anzeigen", "", description_html)
            description_cleaned = re.sub("&nbsp;", " ", description_html)
            print("Description HTML:", description_cleaned.strip())
            listing_data["description"] = description_cleaned.strip()
        except Exception as e:
            print("Error extracting description:", e)
            listing_data["description"] = ""

        # Get the energy certificate value (energy_efficiency_class)
        try:
            await page.querySelectorAll('div[class*="efficiency-class__item--highlighted"]')

            element = await page.querySelector('div[class*="efficiency-class__item--highlighted"] span')
            energy_efficiency_class = await page.evaluate('(element) => element.textContent', element)

            print('Energieeffizienzklasse:', energy_efficiency_class)
            listing_data["energy_efficiency_class"] = energy_efficiency_class.strip()
        except Exception as e:
            listing_data["energy_efficiency_class"] = ""

        # Get the primary energy source (primary_energy_source)
        try:
            await page.querySelectorAll('div[data-test="energy-source"] p:nth-child(2)')

            element = await page.querySelector('div[data-test="energy-source"] p:nth-child(2)')
            energy_sources = await page.evaluate('(element) => element.textContent', element)

            print('Wesentliche Energieträger:', energy_sources)
            listing_data["primary_energy_source"] = energy_sources.strip()
        except Exception as e:
            listing_data["primary_energy_source"] = ""

        print("Platform ID: 2")
        listing_data["platform_id"] = 2  # 1 = Kleinanzeigen, 2 = Immowelt, 3 = Immoscout

        print("Listing is active")
        listing_data["active"] = True

        listed_at = datetime.now().strftime("%Y-%m-%d")
        print("Listed at:", listed_at)
        listing_data["listed_at"] = listed_at

        ################################################################################################
        ############################ LOCATION DATA EXTRACTION STARTS HERE ##############################
        ################################################################################################

        print("=" * 100)
        print("Starting location data extraction...")
        print("=" * 100)

        street_element = await page.querySelector('span[data-cy="address-street"]')
        street = await (await street_element.getProperty("textContent")).jsonValue() if street_element else ""
        if street.strip() == "Straße nicht freigegeben":
            listing_data["street"] = ""
        else:
            listing_data["street"] = street.strip()
        print("Street:", listing_data["street"])

        postal_code_element = await page.querySelector('span[data-cy="address-city"]')
        city_postal_code_element_text = await (await postal_code_element.getProperty("textContent")).jsonValue() if postal_code_element else ""
        postal_code = city_postal_code_element_text.split(' ')[0]
        market_data["postal_code"] = postal_code
        try:
            city = city_postal_code_element_text.split(' ')[1] + city_postal_code_element_text.split(' ')[2]
        except:
            city = city_postal_code_element_text.split(' ')[1]
        print("City : ", city)
        print("Postal Code:", postal_code)
        ################################################################################################
        ############################### EXTRACT AVG MARKET VALUE HOMEDAY ###############################
        ################################################################################################

        print("=" * 100)
        print("Starting HOMEDAY market value extraction...")
        print("=" * 100)

        market_data["market_data_id_conc"] = int(str(market_data["postal_code"]) + str(market_data["property_category_id"]))

        data, count = supabase.table("market_data").select('created_at', 'modified_at').eq("market_data_id_conc", market_data["market_data_id_conc"]).execute()

        try:
            created_at = data[1][0]['created_at']
            print("Created at:", created_at)
            modified_at = data[1][0]['modified_at']
            print("Modified at:", modified_at)
            created_at_year = datetime.strptime(created_at, "%Y-%m-%dT%H:%M:%S.%f+00:00").year
            print("Created at year:", created_at_year)
            if modified_at is None:
                modified_at_year = datetime.strptime(created_at, "%Y-%m-%dT%H:%M:%S.%f+00:00").year
                print("Modified at year:", modified_at_year)
            else:
                modified_at_year = datetime.strptime(modified_at, "%Y-%m-%dT%H:%M:%S+00:00").year
                print("Modified at year:", modified_at_year)
        except:
            data = None

        if data and created_at_year == datetime.today().year and modified_at_year == datetime.today().year:
            print("Market data already exists in Supabase and is from this year.")
            await random_delay()
        else:
            try:
                if street.strip() == "" or street.strip() == "Straße nicht freigegeben":
                    address = f"{postal_code} {city}"
                else:
                    address = f"{street}, {postal_code} {city}"

                url = "https://www.homeday.de/de/preisatlas"
                await page.goto(url, {'timeout': 120000})

                print("Searching for apartments...")

                input_field_selector = '.search-bar__input'
                input_field = await page.querySelector(input_field_selector)

                if input_field:
                    await input_field.type(address.strip())
                    print("Searching for:", address.strip())
                else:
                    print("Input field not found.")
                    await browser.close()
                    await random_delay()
                    return

                await page.keyboard.press('Enter')

                try:
                    await page.waitForNavigation({'timeout': 120000})
                    print("Price page loaded.")
                except Exception as e:
                    print("Navigation Error:", str(e))
                    await browser.close()
                    await random_delay()
                    return

                error_element = await page.querySelector('.error-display__item')
                if error_element:
                    print("Price element not found")
                    market_data["avg_market_value_per_sqm"] = 0
                else:
                    price_block_selector = '.side-panel-list .price-block__price__average'
                    await page.waitForSelector(price_block_selector, {'timeout': 120000})
                    price_element = await page.querySelector(price_block_selector)
                    if price_element:
                        price_text = await page.evaluate('(element) => element.textContent', price_element)
                        price_text = re.sub("[^0-9]", "", price_text)
                        print("Avg. Market Value per Sqm:", price_text.strip())
                        market_data["avg_market_value_per_sqm"] = price_text.strip()
                    else:
                        market_data["avg_market_value_per_sqm"] = 0
                        print("Price element not found")
                        await browser.close()
                        await random_delay()
                        return

                print("Extracting historical market value from HOMEDAY...")

                await page.waitForSelector('svg')
                await page.waitForSelector('.ct-labels')

                year_labels = await page.evaluate('''() => {
                    const labels = document.querySelectorAll('.ct-labels .ct-horizontal');
                    return Array.from(labels).map(label => label.textContent.trim());
                }''')

                data = await page.evaluate('''(year_labels) => {
                    const circles = document.querySelectorAll('circle');
                    const extractedData = [];
                    circles.forEach((circle, index) => {
                        const cx = circle.getAttribute('cx');
                        const cy = circle.getAttribute('cy');
                        const datavalue = circle.getAttribute('datavalue');
                        const year = index < year_labels.length ? year_labels[index] : '';
                        if (year) {
                            extractedData.push({ year, cx, cy, datavalue });
                        }
                    });
                    return extractedData;
                }''', year_labels)

                market_data['avg_market_value_per_sqm_per_year'] = {}

                for circle_data in data:
                    year = circle_data['year']
                    value = int(circle_data['datavalue'])
                    market_data['avg_market_value_per_sqm_per_year'][year] = value
                    print(f"Year: {circle_data['year']}, avg_market_value_per_sqm: {circle_data['datavalue']}")

                print("Starting HOMEDAY avg. rental price extraction...")

                await page.goto(url, {'timeout': 120000})

                await page.waitForSelector('.filter-switcher');
                await page.evaluate('''() => {
                    const tabs = document.querySelectorAll('.filter-switcher .filter-switcher__item');
                    for (const tab of tabs) {
                        if (tab.textContent.trim() === 'Mietpreise') {
                            tab.click();
                            break;
                        }
                    }
                }''')

                print("Searching for apartments...")

                input_field_selector = '.search-bar__input'
                input_field = await page.querySelector(input_field_selector)

                if input_field:
                    await input_field.type(address.strip())
                    print("Searching for:", address.strip())
                else:
                    print("Input field not found.")
                    await browser.close()
                    await random_delay()
                    return

                await page.keyboard.press('Enter')

                try:
                    await page.waitForNavigation({'timeout': 120000})
                    print("Price page loaded.")
                except Exception as e:
                    print("Navigation Error:", str(e))

                error_element = await page.querySelector('.error-display__item')
                if error_element:
                    market_data["avg_rental_price_per_sqm"] = 0
                    print("Price element not found")
                else:
                    price_block_selector = '.side-panel-list .price-block__price__average'
                    await page.waitForSelector(price_block_selector, {'timeout': 120000})
                    price_element = await page.querySelector(price_block_selector)
                    if price_element:
                        price_text = await page.evaluate('(element) => element.textContent', price_element)
                        price_text = price_text.replace(",", ".")
                        price_text = re.sub("[^0-9.]", "", price_text)
                        market_data["avg_rental_price_per_sqm"] = price_text.strip()
                        print("Avg. Rental Price:", price_text.strip())
                    else:
                        print("Price element not found")
                        await browser.close()
                        await random_delay()

                print("Extracting historical rental prices from HOMEDAY...")

                await page.waitForSelector('svg')
                await page.waitForSelector('.ct-labels')

                year_labels = await page.evaluate('''() => {
                    const labels = document.querySelectorAll('.ct-labels .ct-horizontal');
                    return Array.from(labels).map(label => label.textContent.trim());
                }''')

                data = await page.evaluate('''(year_labels) => {
                    const circles = document.querySelectorAll('circle');
                    const extractedData = [];
                    circles.forEach((circle, index) => {
                        const cx = circle.getAttribute('cx');
                        const cy = circle.getAttribute('cy');
                        const datavalue = circle.getAttribute('datavalue');
                        const year = index < year_labels.length ? year_labels[index] : '';
                        if (year) {
                            extractedData.push({ year, cx, cy, datavalue });
                        }
                    });
                    return extractedData;
                }''', year_labels)

                market_data['avg_rental_price_per_sqm_per_year'] = {}

                for circle_data in data:
                    year = circle_data['year']
                    value = circle_data['datavalue']
                    market_data['avg_rental_price_per_sqm_per_year'][year] = value
                    print(f"Year: {circle_data['year']}, avg_rental_price_per_sqm: {circle_data['datavalue']}")

            except Exception as e:
                print("Error in extracting market data:", str(e))
                await random_delay()

        print("Checking data validity...")

        if not listing_data["postal_code"] or not market_data["postal_code"]:
            print("Skipping listing because postal code is empty.")
            await random_delay()
            return
        print("Checking postal code:", listing_data["postal_code"])

        if not market_data["market_data_id_conc"]:
            print("Skipping listing because market_data_id_conc is empty.")
            await random_delay()
            return
        print("Checking market_data_id_conc:", market_data["market_data_id_conc"])

        print("=" * 100)
        print("DONE")
        print("=" * 100)
        if browser:
            await browser.close()
            await random_delay()
        return

    except Exception as e:
        print("Error in process_listing:", str(e))
        await send_message(f"🔴 IWS - Error in process_listing: {str(e)}")
        await random_delay()
    finally:
        if browser:
            await browser.close()

async def main():
    browser = None  # Initialize browser to None
    try:
        print("=" * 100)
        print("Starting main loop...")
        print("=" * 100)

        apartments = []
        await send_message(f"🟢 IWS - Getting APARTMENTS 🏢")

        for page_number in range(1, pages_to_scrape + 1):
            print("=" * 100)
            print("Page:", page_number)
            print("=" * 100)

            apartmentsUrl = f"https://www.immowelt.de/suche/deutschland/wohnungen/kaufen?d=true&sd=DESC&sf=TIMESTAMP&sp={page_number}"
            browser = await open_browser()
            await random_delay()
            page = await browser.newPage()
            await random_delay()
            await page.goto(apartmentsUrl, {'timeout': 120000})

            await page.waitForSelector('.EstateItem-4409d')
            apartments_on_page = await page.querySelectorAll('.EstateItem-4409d')

            for apartment in apartments_on_page:
                link_element = await apartment.querySelector('a')
                link_href = await (await link_element.getProperty("href")).jsonValue()
                parsed_url = urlparse(link_href)
                if parsed_url.scheme in ["http", "https"]:
                    print("Apartment:", link_href)
                    apartments.append(link_href)

            await browser.close()
            await random_delay()  # Introduce a random delay after each request

        await send_message(f"🟢 IWS - Start scraping with {len(apartments)} APARTMENTS 🏢")

        for apartment in apartments:
            try:
                await process_listing(apartment, 1)
                await random_delay()  # Introduce a random delay after each request
            except Exception as e:
                print("Error processing listing:", e)
                if browser:
                    await browser.close()
                await random_delay()

    except Exception as e:
        print("Error in main loop:", str(e))
        await send_message(f"🔴 IWS APARTMENTS - Error in main loop: {str(e)}")

    finally:
        if browser:
            await browser.close()
        await send_message(f"✅ IWS APARTMENTS - stopped")

if __name__ == "__main__":
    asyncio.run(main())
    sys.exit()  # This will cause the container to stop after the script is done
