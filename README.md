# Tamil TV Serial Kodi Addon

Kodi video plugin for browsing and streaming content listed on [TamilTvSerial.com](https://www.tamiltvserial.com/).

## Features

- Latest episodes from the homepage feed
- Browse by channel: Sun TV, Vijay TV, Zee Tamil, and Tamil TV Shows
- Browse individual serial/show categories
- Search episodes
- Resolves episode play links through the site's redirect chain
- Auto-updates via the included Kodi repository

## Requirements

- Kodi 19 (Matrix) or newer with Python 3 support
- Internet connection

## Auto-updates (recommended)

Install the repository **once**. Kodi will then check for addon updates automatically.

1. Download the repository zip from [GitHub Releases](https://github.com/gangop/plugin.video.tamiltvserial/releases) (`repository.tamiltvserial.zip`), or use:
   ```
   https://github.com/gangop/plugin.video.tamiltvserial/releases/latest/download/repository.tamiltvserial.zip
   ```
2. In Kodi: **Settings → Add-ons → Install from zip file** → select the repository zip.
3. Install the video addon from the repo:
   - **Settings → Add-ons → Install from repository → Tamil TV Serial Repository → Video add-ons → Tamil TV Serial**
   - Or install the video addon zip manually (see below); updates still work once the repo is installed.

### Enable automatic updates in Kodi

- **Settings → System → Add-ons → Updates → Auto-update add-ons** → choose **All** or **Only from repositories**
- To check manually: **Add-ons → My add-ons → Tamil TV Serial → Update** (when an update is available)

## Manual install (no repository)

1. Copy `plugin.video.tamiltvserial.zip` to your device from [GitHub Releases](https://github.com/gangop/plugin.video.tamiltvserial/releases).
2. In Kodi, open **Settings → Add-ons → Install from zip file**.
3. Select the zip file.
4. Go to **Add-ons → Video Add-ons → Tamil TV Serial**.

You can also sideload the folder directly into Kodi's `addons` directory:

```
Android/data/org.xbmc.kodi/files/.kodi/addons/plugin.video.tamiltvserial/
```

## Build release artifacts

```bash
chmod +x build_addon.sh build_repo.sh
./build_repo.sh
```

This creates:

- `plugin.video.tamiltvserial.zip` — manual install
- `repository.tamiltvserial.zip` — repository install (enables auto-updates)
- `zips/plugin.video.tamiltvserial-<version>.zip` — hosted update package
- `addons.xml` + checksum files — Kodi repo index

## Project layout

```
plugin.video.tamiltvserial/     # Video addon
repository.tamiltvserial/       # Update repository addon
zips/                           # Hosted addon packages for Kodi repo
addons.xml                      # Kodi repo index
scripts/generate_repo_index.py
```

## Notes

- Episode metadata is loaded from the site's public WordPress REST API.
- Playback links are extracted from each episode page and resolved at play time.
- If an episode fails to play, the source site's redirect or embed format may have changed.

## Disclaimer

This addon is not affiliated with TamilTvSerial.com or any TV broadcaster. Use responsibly and respect content rights in your region.
