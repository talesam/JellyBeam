# JellyBeam

<p align="center">
  <img src="https://github.com/talesam/JellyBeam/blob/main/usr/share/icons/hicolor/scalable/apps/jellybeam.svg" alt="JellyBeam Logo" width="128">
</p>

<p align="center">
  <img src="https://img.shields.io/badge/License-GPL%20v3-blue.svg" alt="License: GPL v3">
  <img src="https://img.shields.io/badge/Platform-Linux-orange.svg" alt="Platform: Linux">
  <img src="https://img.shields.io/badge/Arch%20Linux-ready-1793D1?logo=archlinux&logoColor=white" alt="Arch Linux">
  <img src="https://img.shields.io/badge/Python-3.8+-3776AB?logo=python&logoColor=white" alt="Python 3.8+">
  <img src="https://img.shields.io/badge/GTK-4-4A86CF?logo=gtk&logoColor=white" alt="GTK4">
  <img src="https://img.shields.io/badge/Docker-required-2496ED?logo=docker&logoColor=white" alt="Docker">
</p>

<p align="center">
  <img width="818" height="702" alt="jellybeam" src="https://github.com/user-attachments/assets/767488a3-0004-4656-9eff-374313e8aa0d" />
</p>


**One-click Jellyfin installation for Samsung Tizen and LG webOS TVs and projectors.**

A modern GTK4 application that simplifies installing the Jellyfin client on Samsung Smart TVs running Tizen OS. LG webOS support is planned.

## ✨ Features

- 🔍 **Automatic TV Discovery** - Find Samsung TVs on your network automatically
- 🐳 **Docker Integration** - No manual SDK setup required
- 📦 **One-Click Install** - Simple installation process with progress tracking
- 🖥️ **Modern UI** - Built with GTK4 and Libadwaita for native Linux experience
- 🌐 **Multi-language** - English and Portuguese support

## 📋 Requirements

- Linux
- Docker (installed automatically if missing)
- Samsung TV with **Developer Mode** enabled

## 🚀 Quick Start

### 1. Install Dependencies

```bash
# Arch/Manjaro
sudo pacman -S python-gobject gtk4 libadwaita vte4

# Debian/Ubuntu
sudo apt install python3-gi gir1.2-gtk-4.0 gir1.2-adwaita-1 gir1.2-vte-3.91

# Fedora
sudo dnf install python3-gobject gtk4-devel libadwaita-devel vte291
```

### 2. Clone and Run

```bash
git clone https://github.com/talesam/jellybeam.git
cd jellybeam
python main.py
```

## 📺 Enable Developer Mode on TV

> **For Samsung TVs (2024+)**

1. Go to **Apps** on your TV
2. Scroll to **App Settings**
3. Press **123** on your remote
4. Enter **12345** - Developer Mode menu appears
5. Toggle **Developer Mode** to **On**
6. Enter your computer's IP address
7. **Restart your TV**

## 🎯 Usage

1. **Welcome** - App checks if Docker is installed
2. **Device Setup** - Select your TV from discovered devices or enter IP manually
3. **Install** - Click "Install Jellyfin" and wait for completion
4. **Done** - Open Jellyfin from your TV's app list!

## ⚙️ Configuration

Settings are stored in `~/.config/jellybeam/config.json`:
- Docker image preferences
- Network scanning parameters
- Logging levels

## 🔧 Troubleshooting

| Issue | Solution |
|-------|----------|
| Docker not running | `sudo systemctl start docker` |
| TV not found | Ensure TV and PC are on same network |
| Connection failed | Enable Developer Mode on TV, restart TV |
| Installation hangs | Check Docker logs, ensure disk space |

Logs: `~/.local/share/jellybeam/logs/`

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Submit a Pull Request

## 📄 License

GPL-3.0 License - See [LICENSE](LICENSE)

## 🙏 Acknowledgments

- [Jellyfin](https://jellyfin.org/) - The Free Software Media System
- [install-jellyfin-tizen](https://github.com/Georift/install-jellyfin-tizen) - Original installation scripts
- [GNOME](https://gnome.org/) - GTK4 and Libadwaita
