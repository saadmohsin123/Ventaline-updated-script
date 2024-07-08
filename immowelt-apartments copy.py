# Description: This script scrapes apartments from immowelt.de and stores the data in Supabase.

import asyncio
import logging
from pyppeteer import launch
import pyppeteer.errors
import random
import re
import sys
import requests
import time
from datetime import datetime, time as dt_time
import supabase
from supabase import create_client, Client
from urllib.parse import urlparse

# Imports needed for html file upload
import os

# Imports needed by the price-estimation-api
import json

############################################################################################################
############################################## CONFIGURATION ###############################################
############################################################################################################

local_test = True # Set to False when running on Azure
pages_to_scrape = 1 # Set to 30 when running on Azure

# Set the logging level of pyppeteer to WARNING
logging.getLogger('pyppeteer').setLevel(logging.WARNING)

# supabase: Client = create_client()

user_agents = [ 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_8_2) AppleWebKit/537.17 (KHTML, like Gecko) Chrome/24.0.1309.0 Safari/537.17',
                'Mozilla/5.0 (compatible; MSIE 10.6; Windows NT 6.1; Trident/5.0; InfoPath.2; SLCC1; .NET CLR 3.0.4506.2152; .NET CLR 3.5.30729; .NET CLR 2.0.50727) 3gpp-gba UNTRUSTED/1.0',
                'Opera/12.80 (Windows NT 5.1; U; en) Presto/2.10.289 Version/12.02',
                'Mozilla/4.0 (compatible; MSIE 5.5; Windows NT)',
                'Mozilla/3.0',
                'Mozilla/5.0 (iPhone; U; CPU like Mac OS X; en) AppleWebKit/420+ (KHTML, like Gecko) Version/3.0 Mobile/1A543a Safari/419.3',
                'Mozilla/5.0 (Linux; U; Android 0.5; en-us) AppleWebKit/522+ (KHTML, like Gecko) Safari/419.3',
                'Opera/9.00 (Windows NT 5.1; U; en)']

api_url = '' # TODO Must be changed each time the API gets redeployed

api_headers = {}

############################################################################################################
############################################################################################################
############################################################################################################

async def send_message(message):
    # TOKEN = ""
    # chat_id = ""
    # message_to_send = message
    # url = f""
    print(message)
    # print(requests.get(url).json())

async def random_delay():
    delay = random.uniform(1, 5)  # Random delay between 1 and 5 seconds
    await asyncio.sleep(delay)

async def open_browser():
    browser = None  # Initialize browser to None
    try:
        user_agent = random.choice(user_agents)
        if local_test:
            browser = await launch(headless=False,
                                   slowMo=10,
                                   executablePath='C:\\Users\\03312360099\\Downloads\\chrome-win\\chrome.exe',  # Ensure the correct path
                                   args=['--no-sandbox', '--disable-setuid-sandbox'],
                                   userAgent=user_agent)
        else:
            browser = await launch(headless=False,
                                   executablePath='C:\\Users\\03312360099\\Downloads\\chrome-win\\chrome.exe',  # Ensure the correct path
                                   autoClose=False,
                                   slowMo=10,
                                   args=['--no-sandbox', '--disable-setuid-sandbox'],
                                   userAgent=user_agent)
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
        print("Price:", price.strip())
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
        listing_data["size"] = float(size.strip()) if size.strip() else 0

        rooms_element = await page.querySelector("div.hardfact span.has-font-300")
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

        # TODO: needs to be tested
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

        # TODO: needs to be tested
        if "Bezug" in category_text_1.strip():
            category_text_1 = category_text_1.replace("Bezug", "")
            print("Available from: ", category_text_1.strip())
            listing_data["available_from"] = category_text_1.strip()
        elif "Bezug" in category_text_2.strip():
            category_text_2 = category_text_2.replace("Bezug", "")
            print("Available from: ", category_text_2.strip())
            listing_data["available_from"] = category_text_2.strip()

        # TODO: needs to be tested
    try:
            year_built = ""

            # Try to extract the year of construction from the first location
            year_built_element_1 = await page.querySelector('div.textlist--icon ul li span.color-grey-500')
            year_built_text_1 = await (await year_built_element_1.getProperty("textContent")).jsonValue() if year_built_element_1 else ""
            year_built_1 = year_built_text_1.strip().split(":")[-1].strip()
            if year_built_1.isdigit():
                year_built = year_built_1
                print("Year of construction (first location):", year_built)
    
            if not year_built:
                raise Exception("Year of construction not found in the first location")

    except Exception as e:
            print("Error extracting year of construction from first location:", e)

    try:
        # Try to extract the year of construction from the second location
        year_built_element_2 = await page.querySelector('div.equipment.card-content p.color-grey-500 + p')
        year_built_text_2 = await (await year_built_element_2.getProperty("textContent")).jsonValue() if year_built_element_2 else ""
        if year_built_text_2.strip().isdigit():
            year_built = year_built_text_2.strip()
            print("Year of construction (second location):", year_built)
    except Exception as e:
        print("Error extracting year of construction from second location:", e)

        listing_data["year_built"] = int(year_built) if year_built.isdigit() else ""


        try:
            # TODO: needs to be tested
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
            # TODO: Needs more testing.
            # Click the "Mehr anzeigen" button to expand the content.
            await page.waitForSelector('a[data-test="read-more"]', timeout=50000)
            await page.evaluate('''() => {
                const readMoreButtons = document.querySelectorAll('a[data-test="read-more"]');
                readMoreButtons.forEach(button => button.click());
            }''')

            description_elements = await page.querySelectorAll('div[data-test="description"]')
            description_element = description_elements[1] if len(description_elements) > 1 else None
            description_html = await (await description_element.getProperty("innerHTML")).jsonValue() if description_element else ""
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
        except:
            print("Description HTML: None")
            listing_data["description"] = ""

        # Get the energy certificate value (energy_efficiency_class)
        try:
            # Wait for the content to load
            await page.querySelectorAll('div[class*="efficiency-class__item--highlighted"]')

            # Extract the text content of the Energieeffizienzklasse element
            element = await page.querySelector('div[class*="efficiency-class__item--highlighted"] span')
            energy_efficiency_class = await page.evaluate('(element) => element.textContent', element)

            # Print the extracted value
            print('Energieeffizienzklasse:', energy_efficiency_class)
            listing_data["energy_efficiency_class"] = energy_efficiency_class.strip()
        except Exception as e:
            listing_data["energy_efficiency_class"] = ""

        # Get the primary energy source (primary_energy_source)
        try:
            await page.querySelectorAll('div[data-test="energy-source"] p:nth-child(2)')

            # Extract the text content of the Wesentliche Energieträger element
            element = await page.querySelector('div[data-test="energy-source"] p:nth-child(2)')
            energy_sources = await page.evaluate('(element) => element.textContent', element)

            # Print the extracted value
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

        street_element = await page.querySelector('span[data-test="address-street"]')
        street = await (await street_element.getProperty("textContent")).jsonValue() if street_element else ""
        if street.strip() == "Straße nicht freigegeben":
            listing_data["street"] = ""
        else:
            listing_data["street"] = street.strip()
        print("Street:", listing_data["street"])

        postal_code_element = await page.querySelector('span[data-test="address-postal-code"]')
        postal_code = await (await postal_code_element.getProperty("textContent")).jsonValue() if postal_code_element else ""
        postal_code = re.sub("[^0-9]", "", postal_code.strip())
        print("Postal Code:", postal_code.strip())
        listing_data["postal_code"] = postal_code
        market_data["postal_code"] = postal_code

        city_element = await page.querySelector('span[data-test="address-city"]')
        city = await (await city_element.getProperty("textContent")).jsonValue() if city_element else ""
        city = city.split(postal_code.strip())[-1]
        print("City:", city.strip())

        ################################################################################################
        ############################### EXTRACT AVG MARKET VALUE HOMEDAY ###############################
        ################################################################################################

        print("=" * 100)
        print("Starting HOMEDAY market value extraction...")
        print("=" * 100)

        # Create a new column (as integer) in the market_data table to identify duplocate data by postal_code and property_category_id
        market_data["market_data_id_conc"] = int(str(market_data["postal_code"]) + str(market_data["property_category_id"]))

        # Check if the market data for this listing already exists in supabase
        data, count = supabase.table("market_data").select('created_at', 'modified_at').eq("market_data_id_conc", market_data["market_data_id_conc"]).execute()

        try:
            # This is the output: ('data', [{'created_at': '2023-09-13T03:08:24.675815+00:00', 'modified_at': '2023-10-19T19:33:41+00:00'}])
            # Get the created_at and modified_at dates from the market data
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

        # Check if the market data for this listing already exists in supabase
        # Also check if the market data is from last year or older. If it is, then it should be updated.
        if data and created_at_year == datetime.today().year and modified_at_year == datetime.today().year:
            print("Market data already exists in Supabase and is from this year.")
            await random_delay()
        else:
            try:
                # Put together the address string and skip street if it's not available
                if street.strip() == "" or street.strip() == "Straße nicht freigegeben":
                    address = f"{postal_code} {city}"
                else:
                    address = f"{street}, {postal_code} {city}"

                url = "https://www.homeday.de/de/preisatlas"
                await page.goto(url, {'timeout': 120000})

                print("Searching for apartments...")

                # Locate the input field by class name
                input_field_selector = '.search-bar__input'

                # Check if the input field element is found on the page
                input_field = await page.querySelector(input_field_selector)

                if input_field:
                    # Type data into the input field
                    await input_field.type(address.strip())
                    print("Searching for:", address.strip())
                else:
                    print("Input field not found.")
                    await browser.close()
                    await random_delay()
                    return

                # Hit enter to submit the search
                await page.keyboard.press('Enter')

                # Wait for the new page to load (you can adjust the timeout as needed)
                try:
                    await page.waitForNavigation({'timeout': 120000})
                    print("Price page loaded.")
                except Exception as e:
                    print("Navigation Error:", str(e))
                    # skip this listing and continue with the next one
                    await browser.close()
                    await random_delay()
                    return

                # check if the element class="error-display__item" is present
                error_element = await page.querySelector('.error-display__item')
                if error_element:
                    print("Price element not found")
                    market_data["avg_market_value_per_sqm"] = 0
                else:
                    price_block_selector = '.side-panel-list .price-block__price__average'
                    # add timeout to wait for the price block to load
                    await page.waitForSelector(price_block_selector, {'timeout': 120000})
                    # Retrieve the value from the specified element
                    price_element = await page.querySelector(price_block_selector)
                    if price_element:
                        price_text = await page.evaluate('(element) => element.textContent', price_element)
                        # Remove all non-numeric characters and replace comma with dot
                        price_text = re.sub("[^0-9]", "", price_text)
                        print("Avg. Market Value per Sqm:", price_text.strip())
                        market_data["avg_market_value_per_sqm"] = price_text.strip()
                    else:
                        market_data["avg_market_value_per_sqm"] = 0
                        print("Price element not found")
                        # skip this listing and continue with the next one
                        await browser.close()
                        await random_delay()
                        return

                ##################################################################################
                ################## GET HISTORICAL MARKET VALUE FROM HOMEDAY ######################
                ##################################################################################

                print("Extracting historical market value from HOMEDAY...")

                # Wait for the SVG and year labels to load (you might need to adjust the wait time)
                await page.waitForSelector('svg')
                await page.waitForSelector('.ct-labels')

                # Extract year labels directly using JavaScript
                year_labels = await page.evaluate('''() => {
                    const labels = document.querySelectorAll('.ct-labels .ct-horizontal');
                    return Array.from(labels).map(label => label.textContent.trim());
                }''')

                # Extract data directly using JavaScript
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

                # Print the extracted data with years as labels
                for circle_data in data:
                    year = circle_data['year']
                    value = int(circle_data['datavalue'])
                    market_data['avg_market_value_per_sqm_per_year'][year] = value
                    print(f"Year: {circle_data['year']}, avg_market_value_per_sqm: {circle_data['datavalue']}")

                ################################################################################################
                ############################### EXTRACT AVG RENTAL PRICE HOMEDAY ###############################
                ################################################################################################

                print("=" * 100)
                print("Starting HOMEDAY avg. rental price extraction...")
                print("=" * 100)

                await page.goto(url, {'timeout': 120000})

                # Click on the "Mietpreise" tab
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

                # Locate the input field by class name
                input_field_selector = '.search-bar__input'

                # Check if the input field element is found on the page
                input_field = await page.querySelector(input_field_selector)

                if input_field:
                    # Type data into the input field
                    await input_field.type(address.strip())
                    print("Searching for:", address.strip())
                else:
                    print("Input field not found.")
                    await browser.close()
                    await random_delay()
                    return  # Exit the function

                # Hit enter to submit the search
                await page.keyboard.press('Enter')

                # Wait for the new page to load (you can adjust the timeout as needed)
                try:
                    await page.waitForNavigation({'timeout': 120000})
                    print("Price page loaded.")
                except Exception as e:
                    print("Navigation Error:", str(e))

                # check if the element class="error-display__item" is present
                error_element = await page.querySelector('.error-display__item')
                if error_element:
                    market_data["avg_rental_price_per_sqm"] = 0
                    print("Price element not found")
                else:
                    # Wait for the price block to load
                    price_block_selector = '.side-panel-list .price-block__price__average'
                    await page.waitForSelector(price_block_selector, {'timeout': 120000})
                    # Retrieve the value from the specified element
                    price_element = await page.querySelector(price_block_selector)
                    if price_element:
                        price_text = await page.evaluate('(element) => element.textContent', price_element)
                        # Replace comma with dot
                        price_text = price_text.replace(",", ".")
                        # Replace everything except numbers and dot
                        price_text = re.sub("[^0-9.]", "", price_text)
                        market_data["avg_rental_price_per_sqm"] = price_text.strip()
                        print("Avg. Rental Price:", price_text.strip())
                    else:
                        print("Price element not found")
                        # skip this listing and continue with the next one
                        await browser.close()
                        await random_delay()

                ##################################################################################
                ############### GET HISTORICAL AVG RENTAL PRICE FROM HOMEDAY #####################
                ##################################################################################

                print("=" * 100)
                print("Extracting historical rental prices from HOMEDAY...")
                print("=" * 100)

                # Wait for the SVG and year labels to load (you might need to adjust the wait time)
                await page.waitForSelector('svg')
                await page.waitForSelector('.ct-labels')

                # Extract year labels directly using JavaScript
                year_labels = await page.evaluate('''() => {
                    const labels = document.querySelectorAll('.ct-labels .ct-horizontal');
                    return Array.from(labels).map(label => label.textContent.trim());
                }''')

                # Extract data directly using JavaScript
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

                # Print the extracted data with years as labels
                for circle_data in data:
                    year = circle_data['year']
                    value = circle_data['datavalue']
                    market_data['avg_rental_price_per_sqm_per_year'][year] = value
                    print(f"Year: {circle_data['year']}, avg_rental_price_per_sqm: {circle_data['datavalue']}")

            except Exception as e:
                print("Error in extracting market data:", str(e))
                # Skip this listing and continue with the next one
                await random_delay()

        ##################################################################################
        ############################# DATA VALIDITY CHECKS ###############################
        ##################################################################################

        print("=" * 100)
        print("Checking data validity...")
        print("=" * 100)

        # Check if in all objects listing_data and market_data the postal_code field is not empty
        if not listing_data["postal_code"] or not market_data["postal_code"]:
            print("Skipping listing because postal code is empty.")
            await random_delay()
            return
        print("Checking postal code:", listing_data["postal_code"])

        # Check if market_data["market_data_id_conc"] is not empty
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
        # Log the error and continue with the next iteration
        print("Error in process_listing:", str(e))
        # Send a Telegram notification
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

            # Get all listing elements
            await page.waitForSelector('.EstateItem-4409d')
            apartments_on_page = await page.querySelectorAll('.EstateItem-4409d')

            # Loop through all listings on the page and extract the URLs
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

        # Loop through all listings on the page, extract, and write the data to Supabase
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
