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
    res = subprocess.run(cmd, shell=shell)
    if check and res.returncode != 0:
        print(f"[!] Error al ejecutar: {cmd}")
        sys.exit(1)


def ask_inputs():
    """Solicita los datos del usuario para la instalación."""
    print("=" * 60)
    print("  INSTALADOR AUTOMÁTICO DE ARCH LINUX + BTRFS + HYPRLAND")
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

    username = input("Nombre de usuario para el sistema: ").strip().lower()

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

    return disk, username, password


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
        # En BIOS necesitamos una partición BIOS Boot para GRUB en tablas GPT
        run(f"parted -s {disk} mkpart non-fs 1MiB 3MiB")
        run(f"parted -s {disk} set 1 bios_grub on")
        run(f"parted -s {disk} mkpart primary btrfs 3MiB 100%")

    # Forzar actualización ignorando errores en lecturas de CD-ROM /dev/sr0
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


def install_base_packages():
    """Instala el kernel, paquetes base, soporte de hardware y paquetes de desarrollo."""
    base_pkgs = [
        "base",
        "linux",
        "linux-firmware",
        "btrfs-progs",
        "neovim",
        "sudo",
        "networkmanager",
        "git",
        "curl",
        "wget",
        "base-devel",
        "pacman-contrib",
    ]

    hardware_pkgs = [
        "wlr-randr",
        "kanshi",
        "brightnessctl",
        "xdg-desktop-portal-hyprland",
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

    hyprland_pkgs = [
        "hyprland",
        "waybar",
        "kitty",
        "rofi-wayland",
        "dunst",
        "polkit-kde-agent",
        "qt5-wayland",
        "qt6-wayland",
        "sddm",
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
    ]

    boot_pkgs = ["grub", "efibootmgr", "snapper", "snap-pac"]

    all_pkgs = base_pkgs + hardware_pkgs + hyprland_pkgs + dev_pkgs + boot_pkgs

    print("\n[+] Instalando paquetes en /mnt (esto puede demorar unos minutos)...")
    run(["pacstrap", "-K", "/mnt"] + all_pkgs)

    print("\n[+] Generando fstab...")
    run("genfstab -U /mnt >> /mnt/etc/fstab", shell=True)


def configure_system(username, password, disk):
    is_efi = os.path.exists("/sys/firmware/efi")

    if is_efi:
        grub_cmd = "grub-install --target=x86_64-efi --efi-directory=/boot --bootloader-id=GRUB"
    else:
        grub_cmd = f"grub-install --target=i386-pc {disk}"

    chroot_script = f"""#!/bin/bash
set -e

# Configuración Horaria y Localización
ln -sf /usr/share/zoneinfo/America/Argentina/Cordoba /etc/localtime
hwclock --systohc
echo "en_US.UTF-8 UTF-8" >> /etc/locale.gen
echo "es_AR.UTF-8 UTF-8" >> /etc/locale.gen
locale-gen
echo "LANG=es_AR.UTF-8" > /etc/locale.conf
echo "arch-hyprland" > /etc/hostname

# Configuración de usuarios
echo "root:{password}" | chpasswd
useradd -m -G wheel,docker,lp,scanner -s /bin/bash {username}
echo "{username}:{password}" | chpasswd
echo "%wheel ALL=(ALL:ALL) ALL" >> /etc/sudoers

# Habilitar Servicios del Sistema
systemctl enable NetworkManager
systemctl enable sddm
systemctl enable cups
systemctl enable bluetooth
systemctl enable docker

# Instalación Dinámica de GRUB (EFI o BIOS)
{grub_cmd}
grub-mkconfig -o /boot/grub/grub.cfg

# Configurar Snapper para la raíz
snapper -c root create-config /

# Ajustar límites de snapshots para no agotar espacio
sed -i 's/NUMBER_LIMIT_MIN="[0-9]*"/NUMBER_LIMIT_MIN="2"/' /etc/snapper/configs/root
sed -i 's/NUMBER_LIMIT_MAX="[0-9]*"/NUMBER_LIMIT_MAX="5"/' /etc/snapper/configs/root
sed -i 's/TIMELINE_LIMIT_HOURLY="[0-9]*"/TIMELINE_LIMIT_HOURLY="0"/' /etc/snapper/configs/root
sed -i 's/TIMELINE_LIMIT_DAILY="[0-9]*"/TIMELINE_LIMIT_DAILY="3"/' /etc/snapper/configs/root
sed -i 's/TIMELINE_LIMIT_WEEKLY="[0-9]*"/TIMELINE_LIMIT_WEEKLY="2"/' /etc/snapper/configs/root
sed -i 's/TIMELINE_LIMIT_MONTHLY="[0-9]*"/TIMELINE_LIMIT_MONTHLY="0"/' /etc/snapper/configs/root
sed -i 's/TIMELINE_LIMIT_YEARLY="[0-9]*"/TIMELINE_LIMIT_YEARLY="0"/' /etc/snapper/configs/root

systemctl enable snapper-cleanup.timer
systemctl enable snapper-timeline.timer

# Compilación de yay y grub-btrfs
su - {username} -c "
git clone https://aur.archlinux.org/yay.git /tmp/yay && \
cd /tmp/yay && \
makepkg -si --noconfirm
"
yay -S --noconfirm grub-btrfs
systemctl enable grub-btrfsd
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

    disk, username, password = ask_inputs()
    partition_and_mount(disk)
    install_base_packages()
    configure_system(username, password, disk)

    print("\n" + "=" * 60)
    print(" ¡INSTALACIÓN COMPLETADA CON ÉXITO!")
    print(" Puedes desmontar la partición y reiniciar con: umount -R /mnt && reboot")
    print("=" * 60)


if __name__ == "__main__":
    main()
