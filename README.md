
# ZONE X Bot (Exotic Fruits)

Bot Telegram cu meniu de produse, recenzii, referal+portofel (puncte), DICTIONAR (postări publice), broadcast admin,
și schelet pentru plăți crypto (Coinbase) – activabile ulterior.

## Setup local
1) Copiază `.env.template` în `.env` și completează valorile.
2) Instalează dependențele:
   ```bash
   pip install -r requirements.txt
   ```
3) Rulează:
   ```bash
   python main.py
   ```

## Deploy pe Render
- Repo pe GitHub cu aceste fișiere.
- `render.yaml` permite Blueprint deploy.
- La primul deploy, setează env vars în Render Dashboard (nu urca `.env`).
- După ce primești URL-ul public (ex. https://zonex-bot.onrender.com),
  setează `BASE_PUBLIC_URL` cu acel URL și redeploy.

## Comenzi utile
- Utilizator: /start, /menu, /wallet, /ref, /dictionary, /review
- Admin: /admin, /add, /setprice, /setstock, /del, /list, /orders, /postdict, /broadcast

## Note
- Baza de date: SQLite `zonex.db` (persistă în container cât timp serviciul nu e redeployat). Pentru producție folosește un volum/disc persistent sau Postgres.
