# AllVideoDL Backend (yt-dlp, Flask, Render)

## Deploy on Render
1. Push this folder to a GitHub repo.
2. Render dashboard → New → Web Service → connect the repo.
3. Environment: **Docker** (Render auto-detects the `Dockerfile`).
4. Instance type: free tier is fine to start; note free tier sleeps after
   inactivity, so the first request after idle will be slow.
5. Deploy. Your base URL will look like `https://your-service.onrender.com`.

## Known risk (flagged, not fixed here)
This build uses yt-dlp directly for every platform, including YouTube.
Render's IPs are shared/cloud IPs, and YouTube specifically rate-limits and
blocks known cloud IP ranges — this is the exact issue the previous backend
hit. Nothing in this code works around that; if YouTube extraction starts
failing with "Sign in to confirm you're not a bot" or HTTP 429 errors, that's
why. The fix, if/when needed, is either rotating residential proxies or
switching YouTube/Instagram to your paid RapidAPI keys.

## API

### `POST /api/info`
Request:
```json
{ "url": "https://..." }
```
Response:
```json
{
  "title": "...",
  "thumbnail": "https://...",
  "duration": 225,
  "source": "Youtube",
  "formats": [
    { "format_id": "137", "label": "1080p", "ext": "mp4", "has_audio": false, "filesize_approx": 125829120 },
    { "format_id": "22",  "label": "720p",  "ext": "mp4", "has_audio": true,  "filesize_approx": 62914560 },
    { "format_id": "bestaudio", "label": "Audio Only", "ext": "mp3", "has_audio": true, "filesize_approx": null }
  ]
}
```
Show `formats` in the app exactly like the quality-picker UI in your
screenshot (1080p / 720p / 480p / Audio Only).

### `GET /api/download?url=<encoded_url>&format_id=<id>`
Streams the file directly as an attachment. Call this when the user taps
"Download" after picking a quality. The Android app can point its download
manager straight at this URL.

## Local test
```bash
pip install -r requirements.txt
python app.py
# then:
curl -X POST localhost:5000/api/info -H "Content-Type: application/json" \
  -d '{"url":"https://youtu.be/VIDEO_ID"}'
```
