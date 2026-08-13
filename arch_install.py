#!/usr/bin/env python3
import getpass
import os
import subprocess
import sys


def run(cmd, shell=False, check=True):
    """Ejecuta un comando en el sistema."""
    if isinstance(cmd, str) and not shell:
        cmd = cmd.split()
    print(f"\n--> Ejecutando: {cmd if isinstance(cmd, str) else ' '.join(cmd)}")
    res = subprocess.run(
        cmd, shell=shell, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )
    if check and res.returncode != 0:
        print(f"[!] Error al ejecutar: {cmd}\n{res.stderr}")
        sys.exit(1)
    return res.stdout


def detect_cpu_microcode():
    """Detecta el fabricante del procesador e instala el microcódigo adecuado."""
    try:
        with open("/proc/cpuinfo", "r") as f:
            cpu_data = f.read()
            if "GenuineIntel" in cpu_data:
                print("[+] CPU Intel detectada. Agregando intel-ucode.")
                return ["intel-ucode"]
            elif "AuthenticAMD" in cpu_data:
                print("[+] CPU AMD detectada. Agregando amd-ucode.")
                return ["amd-ucode"]
    except Exception as e:
        print(f"[!] No se pudo detectar la CPU: {e}")
    return []


def detect_gpu_drivers():
    """Detecta la tarjeta gráfica instalada mediante lspci e incluye los drivers necesarios."""
    gpu_pkgs = (
        ["mesa", "lib32-mesa"] if os.path.exists("/etc/pacman.conf") else ["mesa"]
    )
    try:
        res = subprocess.run("lspci", shell=True, stdout=subprocess.PIPE, text=True)
        lspci_out = res.stdout.lower()

        if "nvidia" in lspci_out:
            print("[+] GPU NVIDIA detectada. Agregando controladores de NVIDIA.")
            gpu_pkgs.extend(["nvidia", "nvidia-utils", "nvidia-settings"])
        if "amd" in lspci_out or "radeon" in lspci_out:
            print("[+] GPU AMD detectada. Agregando controladores Vulkan de AMD.")
            gpu_pkgs.extend(["xf86-video-amdgpu", "vulkan-radeon"])
        if "intel" in lspci_out:
            print("[+] GPU Intel detectada. Agregando controladores de Intel.")
            gpu_pkgs.extend(["intel-media-driver", "vulkan-intel"])
    except Exception as e:
        print(
            f"[!] Error detectando la GPU: {e}. Se instalarán paquetes básicos de Mesa."
        )

    return list(set(gpu_pkgs))


def ask_inputs():
    """Solicita los datos del usuario para la instalación."""
    print("=" * 60)
    print("  INSTALADOR AUTOMÁTICO DE ARCH LINUX + BTRFS + SNAPSHOTS")
    print("=" * 60)

    # Mostrar discos disponibles
    run("lsblk -d -n -o NAME,SIZE,TYPE,MODEL")
    print("-" * 60)

    disk = input("Ingresa el disco a formatear (ejemplo: sda, nvme0n1, vda): ").strip()
    if not disk.startswith("/dev/"):
        disk = f"/dev/{disk}"

    if not os.path.exists(disk):
        print(f"[!] El disco {disk} no existe.")
        sys.exit(1)

    print("\n" + "-" * 60)
    print(" Selecciona el Entorno de Escritorio / Window Manager:")
    print("  1) GNOME")
    print("  2) KDE Plasma")
    print("  3) Hyprland")
    print("-" * 60)

    desktop_choice = ""
    while desktop_choice not in ["1", "2", "3"]:
        desktop_choice = input("Ingresa una opción (1, 2 o 3): ").strip()

    username = input("\nNombre de usuario para el sistema: ").strip().lower()

    while True:
        password = getpass.getpass("Contraseña para el usuario: ")
        password_confirm = getpass.getpass("Confirma la contraseña: ")
        if password == password_confirm and password != "":
            break
        print("[!] Las contraseñas no coinciden o están vacías. Reintenta.")

    print("\n" + "!" * 60)
    print(f" ADVERTENCIA: Se borrarán TODOS los datos en {disk}")
    print("!" * 60)
    confirm = input("¿Deseas continuar? (escribe 'SI' para confirmar): ")
    if confirm != "SI":
        print("Cancelando instalación.")
        sys.exit(0)

    return disk, desktop_choice, username, password


def partition_and_mount(disk):
    is_efi = os.path.exists("/sys/firmware/efi")
    p1 = f"{disk}p1" if "nvme" in disk or "mmcblk" in disk else f"{disk}1"
    p2 = f"{disk}p2" if "nvme" in disk or "mmcblk" in disk else f"{disk}2"

    print("\n[+] Desmontando /mnt por si hay ejecuciones previas...")
    run("umount -R /mnt", check=False)
    run("swapoff -a", check=False)

    print("\n[+] Limpiando y particionando el disco...")
    run(f"sgdisk --zap-all {disk}")
    run(f"parted -s {disk} mklabel gpt")

    if is_efi:
        run(f"parted -s {disk} mkpart ESP fat32 1MiB 1024MiB")
        run(f"parted -s {disk} set 1 esp on")
        run(f"parted -s {disk} mkpart primary btrfs 1024MiB 100%")
    else:
        # En BIOS se requiere una partición BIOS Boot para GRUB con GPT
        run(f"parted -s {disk} mkpart non-fs 1MiB 3MiB")
        run(f"parted -s {disk} set 1 bios_grub on")
        run(f"parted -s {disk} mkpart primary btrfs 3MiB 100%")

    run(f"partprobe {disk}", check=False)

    print("\n[+] Formateando particiones...")
    if is_efi:
        run(f"mkfs.fat -F32 {p1}")
    run(f"mkfs.btrfs -f {p2}")

    print("\n[+] Creando subvolúmenes Btrfs...")
    run(f"mount {p2} /mnt")
    for sub in ["@", "@home", "@snapshots", "@log", "@pkg"]:
        run(f"btrfs subvolume create /mnt/{sub}")
    run("umount /mnt")

    print("\n[+] Montando subvolúmenes en /mnt...")
    btrfs_opts = "noatime,compress=zstd:1,space_cache=v2"
    run(f"mount -o {btrfs_opts},subvol=@ {p2} /mnt")

    directories = [
        "/mnt/boot",
        "/mnt/home",
        "/mnt/.snapshots",
        "/mnt/var/log",
        "/mnt/var/cache/pacman/pkg",
    ]
    for d in directories:
        os.makedirs(d, exist_ok=True)

    if is_efi:
        run(f"mount {p1} /mnt/boot")

    run(f"mount -o {btrfs_opts},subvol=@home {p2} /mnt/home")
    run(f"mount -o {btrfs_opts},subvol=@snapshots {p2} /mnt/.snapshots")
    run(f"mount -o {btrfs_opts},subvol=@log {p2} /mnt/var/log")
    run(f"mount -o {btrfs_opts},subvol=@pkg {p2} /mnt/var/cache/pacman/pkg")


def install_base_packages(desktop_choice):
    """Instala el kernel, paquetes base, soporte de hardware, red, fuentes y multimedia."""
    base_pkgs = [
        "base",
        "linux",
        "linux-firmware",
        "btrfs-progs",
        "neovim",
        "sudo",
        "networkmanager",
        "iwd",
        "wpa_supplicant",
        "modemmanager",
        "dialog",
        "git",
        "curl",
        "wget",
        "base-devel",
        "pacman-contrib",
    ]

    hardware_pkgs = [
        "brightnessctl",
        "cups",
        "cups-pdf",
        "system-config-printer",
        "sane",
        "simple-scan",
        "hplip",
        "pipewire",
        "pipewire-alsa",
        "pipewire-pulse",
        "pipewire-jack",
        "wireplumber",
        "bluez",
        "bluez-utils",
    ]

    media_and_fonts = [
        "ttf-dejavu",
        "ttf-liberation",
        "noto-fonts",
        "noto-fonts-emoji",
        "ffmpeg",
        "gst-plugins-base",
        "gst-plugins-good",
        "gst-plugins-bad",
        "gst-plugins-ugly",
        "ntfs-3g",
        "exfatprogs",
        "dosfstools",
        "unzip",
        "p7zip",
        "unrar",
        "tar",
        "gzip",
    ]

    # Detección dinámica de microcódigo y GPUs
    ucode_pkgs = detect_cpu_microcode()
    gpu_pkgs = detect_gpu_drivers()

    # Selección según el escritorio
    if desktop_choice == "1":  # GNOME
        desktop_pkgs = [
            "gnome",
            "gnome-tweaks",
            "gdm",
            "xdg-desktop-portal-gnome",
        ]
    elif desktop_choice == "2":  # KDE Plasma
        desktop_pkgs = [
            "plasma-meta",
            "kde-applications",
            "sddm",
            "xdg-desktop-portal-kde",
        ]
    elif desktop_choice == "3":  # Hyprland
        desktop_pkgs = [
            "hyprland",
            "waybar",
            "kitty",
            "rofi-wayland",
            "dunst",
            "polkit-kde-agent",
            "qt5-wayland",
            "qt6-wayland",
            "sddm",
            "wlr-randr",
            "kanshi",
            "xdg-desktop-portal-hyprland",
        ]

    dev_pkgs = [
        "python",
        "python-pip",
        "clang",
        "gdb",
        "cmake",
        "docker",
        "docker-compose",
        "code",
        "go",
    ]

    # Herramientas Btrfs y recuperación
    boot_pkgs = ["grub", "efibootmgr", "snapper", "snap-pac"]

    all_pkgs = (
        base_pkgs
        + ucode_pkgs
        + gpu_pkgs
        + hardware_pkgs
        + media_and_fonts
        + desktop_pkgs
        + dev_pkgs
        + boot_pkgs
    )

    print("\n[+] Instalando paquetes en /mnt (esto puede demorar)...")
    run(["pacstrap", "-K", "/mnt"] + all_pkgs)

    print("\n[+] Generando fstab...")
    run("genfstab -U /mnt >> /mnt/etc/fstab", shell=True)


def configure_system(username, password, disk, desktop_choice):
    is_efi = os.path.exists("/sys/firmware/efi")

    if is_efi:
        grub_cmd = "grub-install --target=x86_64-efi --efi-directory=/boot --bootloader-id=GRUB"
    else:
        grub_cmd = f"grub-install --target=i386-pc {disk}"

    dm_service = "gdm" if desktop_choice == "1" else "sddm"

    chroot_script = f"""#!/bin/bash
set -e

# Configuración Horaria y Localización
ln -sf /usr/share/zoneinfo/America/Argentina/Cordoba /etc/localtime
hwclock --systohc
echo "en_US.UTF-8 UTF-8" >> /etc/locale.gen
echo "es_AR.UTF-8 UTF-8" >> /etc/locale.gen
locale-gen
echo "LANG=es_AR.UTF-8" > /etc/locale.conf
echo "arch-system" > /etc/hostname

# Configuración de usuarios
echo "root:{password}" | chpasswd
useradd -m -G wheel,docker,lp,scanner -s /bin/bash {username}
echo "{username}:{password}" | chpasswd

# Permitir a los miembros del grupo wheel ejecutar sudo sin contraseña
echo "%wheel ALL=(ALL:ALL) NOPASSWD: ALL" >> /etc/sudoers

# Habilitar Servicios del Sistema
systemctl enable NetworkManager
systemctl enable ModemManager
systemctl enable {dm_service}
systemctl enable cups
systemctl enable bluetooth
systemctl enable docker

# Instalación Dinámica de GRUB (EFI o BIOS)
{grub_cmd}

# Configuración manual de Snapper para / (evita fallo de D-Bus en chroot)
mkdir -p /etc/snapper/configs
cat << 'EOF' > /etc/snapper/configs/root
SUBVOLUME="/"
FSTYPE="btrfs"
SPACE_LIMIT="0.5"
FREE_LIMIT="0.2"
ALLOW_USERS=""
ALLOW_GROUPS="wheel"
SYNC_ACL="no"
BACKGROUND_COMPARISON="yes"
NUMBER_CLEANUP="yes"
NUMBER_MIN_AGE="0"
NUMBER_LIMIT_MIN="2"
NUMBER_LIMIT_MAX="10"
TIMELINE_CREATE="yes"
TIMELINE_CLEANUP="yes"
TIMELINE_MIN_AGE="1800"
TIMELINE_LIMIT_HOURLY="5"
TIMELINE_LIMIT_DAILY="7"
TIMELINE_LIMIT_WEEKLY="4"
TIMELINE_LIMIT_MONTHLY="12"
TIMELINE_LIMIT_YEARLY="0"
EMPTY_PRE_POST_CLEANUP="yes"
EMPTY_PRE_POST_MIN_AGE="1800"
EOF

echo 'SNAPPER_CONFIGS="root"' > /etc/conf.d/snapper

# Habilitar timers de Snapper para snapshots periódicos y limpieza
systemctl enable snapper-cleanup.timer
systemctl enable snapper-timeline.timer

# Compilación e instalación de yay y grub-btrfs desde el AUR
su - {username} -c "
git clone https://aur.archlinux.org/yay.git /tmp/yay && \
cd /tmp/yay && \
makepkg -si --noconfirm
"
su - {username} -c "yay -S --noconfirm grub-btrfs"

# Habilitar el daemon de grub-btrfs para actualizar GRUB automáticamente en cada snapshot
systemctl enable grub-btrfsd

# Regenerar configuración de GRUB incorporando microcódigo y grub-btrfs
grub-mkconfig -o /boot/grub/grub.cfg
"""

    with open("/mnt/setup.sh", "w") as f:
        f.write(chroot_script)

    run("chmod +x /mnt/setup.sh")
    print("\n[+] Ejecutando configuración dentro de arch-chroot...")
    run("arch-chroot /mnt /setup.sh")
    os.remove("/mnt/setup.sh")


def main():
    if os.geteuid() != 0:
        print("[!] Este script debe ejecutarse con permisos de ROOT.")
        sys.exit(1)

    disk, desktop_choice, username, password = ask_inputs()
    partition_and_mount(disk)
    install_base_packages(desktop_choice)
    configure_system(username, password, disk, desktop_choice)

    print("\n" + "=" * 60)
    print(" ¡INSTALACIÓN COMPLETADA CON ÉXITO!")
    print(
        " Sistema completo instalado con soporte multimedia, red, drivers y snapshots Btrfs."
    )
    print(" Puedes desmontar la partición y reiniciar con: umount -R /mnt && reboot")
    print("=" * 60)


if __name__ == "__main__":
    main()
