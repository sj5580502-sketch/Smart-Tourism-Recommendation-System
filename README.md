# Smart Tourism — 10 Correct Places

This version deliberately contains only 10 Jharkhand destinations.

## Image fix
Each place searches Wikimedia Commons using its exact place + city name at startup. The image URL is saved separately for each destination, so the same generic image is not assigned to every card.

## Weather
Uses Open-Meteo + its geocoding API. No API key is required.

## Run
```bash
pip install -r requirements.txt
python app.py
```
Open http://127.0.0.1:5000

Demo admin: admin@smarttourism.com / admin123

Image sources are loaded from Wikimedia Commons where available; the source search term is destination-specific.

Naulakha Mandir is pinned to the verified Deoghar photograph `Naulakha Temple, Deoghar, Jharkhand.jpg` from Wikimedia Commons; the app no longer uses a map image or a generic temple result for that card.
