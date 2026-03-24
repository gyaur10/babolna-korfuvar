# wake_streamlit.py
import os
import time
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By

APP_URLS = [
    os.getenv("STREAMLIT_APP_URL", "https://babolna-korfuvar-dv539ucm8ezkffgrnfkf6k.streamlit.app/"),
]

def wake_up(url: str):
    chrome_options = Options()
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--log-level=3")

    driver = webdriver.Chrome(options=chrome_options)

    try:
        driver.get(url)
        time.sleep(15)

        try:
            wake_button = driver.find_element(By.XPATH, "//button[contains(., 'Wake up')]")
            wake_button.click()
            time.sleep(15)
        except Exception:
            pass

        title = driver.title
        print(f"Opened {url}, title: {title}")

    finally:
        driver.quit()

if __name__ == "__main__":
    for url in APP_URLS:
        print(f"Waking: {url}")
        wake_up(url)
