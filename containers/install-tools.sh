#!/bin/bash
set -euo pipefail
if [ -f /opt/environment/spack.yaml ] && ! cmp -s /input/spack.yaml /opt/environment/spack.yaml; then
    rm -rf /opt/environment
fi
mkdir -p /opt/environment /export
cp /input/spack.yaml /opt/environment/spack.yaml
if [ -f /input/spack.lock ] && [ ! -f /opt/environment/spack.lock ]; then
    cp /input/spack.lock /opt/environment/spack.lock
fi
apt-get update
apt-get install -y --no-install-recommends software-properties-common \
    libgl1 libglu1-mesa libegl1 libgl1-mesa-dri libglx-mesa0 libegl-mesa0 \
    libxrender1 libxkbcommon-x11-0 libxcb-cursor0 libxcb-icccm4 libxcb-keysyms1 \
    libx11-xcb1 libxcb-xinerama0 libxext6 libsm6 libice6 libfontconfig1 \
    xvfb xauth x11-utils libopengl0 libgomp1 libasound2t64 libnss3 libdbus-1-3 \
    libxcomposite1 libxcursor1 libxi6 libxtst6 libxrandr2 libxdamage1
if ! command -v kicad-cli >/dev/null; then
    add-apt-repository -y ppa:kicad/kicad-10.0-releases
    apt-get update
    apt-get install -y --install-recommends kicad=10.0.7~ubuntu24.04.1 \
        kicad-symbols=10.0.7~ubuntu24.04.1 kicad-footprints=10.0.7~ubuntu24.04.1 \
        kicad-packages3d=10.0.7~ubuntu24.04.1 python3-numpy
fi
spack -e /opt/environment concretize
cp /opt/environment/spack.lock /export/spack.lock
# FLTK 1.3.7 autogen.sh otherwise runs configure before Spack supplies
# --disable-xft, incorrectly requiring undeclared FreeType/Xft headers.
# Let each package recipe run its configured build options after bootstrapping.
NOCONFIGURE=1 spack -e /opt/environment install -j "${BUILD_JOBS:-2}" --fail-fast
/usr/bin/python3 /input/install-assets.py /input/pins.json
spack -e /opt/environment find --json > /export/packages.json
cp /opt/environment/spack.yaml /export/spack.yaml
cp /opt/environment/spack.lock /export/spack.lock
dpkg-query -W > /export/apt-packages.txt
kicad-cli version
rm -rf /var/lib/apt/lists/*
