# wake_streamlit.py
import time
from selenium import webdriver
from selenium.webdriver.chrome.options import Options

APP_URL = "https://babolna-korfuvar-dv539ucm8ezkffgrnfkf6k.streamlit.app"  # <- saját URL

def main():
    chrome_options = Options()
    # Nem állítunk be binary_location-t, a setup-chrome által telepített "chrome" elérhető
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--window-size=1920,1080")

    # NINCS Service, NINCS driver path -> Selenium Manager választ megfelelő drivert
    driver = webdriver.Chrome(options=chrome_options)

    try:
        print(f"Opening {APP_URL}")
        driver.get(APP_URL)
        time.sleep(20)
        print("Page title:", driver.title)
    finally:
        driver.quit()

if __name__ == "__main__":
    main()
