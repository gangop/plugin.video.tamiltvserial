# Tamil TV Serial Kodi Addon

Kodi video plugin for browsing and streaming content listed on [TamilTvSerial.com](https://www.tamiltvserial.com/).

## Features

- Latest episodes from the homepage feed
- Browse by channel: Sun TV, Vijay TV, Zee Tamil, and Tamil TV Shows
- Browse individual serial/show categories
- Search episodes
- Resolves episode play links through the site's redirect chain

## Requirements

- Kodi 19 (Matrix) or newer with Python 3 support
- Internet connection

## Install on Android Kodi

1. Copy `plugin.video.tamiltvserial.zip` to your Android device.
2. In Kodi, open **Settings → Add-ons → Install from zip file**.
3. Select the zip file.
4. Go to **Add-ons → Video Add-ons → Tamil TV Serial**.

You can also sideload the folder directly into Kodi's `addons` directory:

```
Android/data/org.xbmc.kodi/files/.kodi/addons/plugin.video.tamiltvserial/
```

## Build the install zip

```bash
chmod +x build_addon.sh
./build_addon.sh
```

## Project layout

```
plugin.video.tamiltvserial/
  addon.xml
  addon.py
  resources/
    lib/
      constants.py
      utils.py
      scraper.py
      stream_resolver.py
      router.py
    settings.xml
    icon.png
```

## Notes

- Episode metadata is loaded from the site's public WordPress REST API.
- Playback links are extracted from each episode page and resolved at play time.
- If an episode fails to play, the source site's redirect or embed format may have changed.

## Disclaimer

This addon is not affiliated with TamilTvSerial.com or any TV broadcaster. Use responsibly and respect content rights in your region.
