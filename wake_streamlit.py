# wake_streamlit.py
import os
import time
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service

APP_URL = "https://babolna-korfuvar-dv539ucm8ezkffgrnfkf6k.streamlit.app"  # <- saját URL

def main():
    chrome_binary = os.getenv("CHROME_PATH")          # GitHub Actions-ből jön
    chromedriver_path = os.getenv("CHROMEDRIVER_PATH")  # GitHub Actions-ből jön

    chrome_options = Options()
    if chrome_binary:
        chrome_options.binary_location = chrome_binary

    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--window-size=1920,1080")

    service = Service(executable_path=chromedriver_path) if chromedriver_path else None

    driver = webdriver.Chrome(service=service, options=chrome_options)

    try:
        print(f"Opening {APP_URL}")
        driver.get(APP_URL)
        time.sleep(20)
        print("Page title:", driver.title)
    finally:
        driver.quit()

if __name__ == "__main__":
    main()
