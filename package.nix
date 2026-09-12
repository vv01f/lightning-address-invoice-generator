{
  lib,
  stdenv,
  buildPythonApplication,
  fetchFromGitHub,
  setuptools,
  wheel,
  requests,
  bech32,
  pyside6,
  qrcode,
  pillow,
  websocket-client,
  makeDesktopItem,
  librsvg,
  icnsutil ? null,
  srcOverride ? null,
}:

let
  githubSrc = fetchFromGitHub {
    owner = "vv01f";
    repo = "lightning-address-invoice-generator";
    rev = "9abcb8d7cd9635e887b0f755ceebf604575507fc";
    hash = "sha256-AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=";
    #~ hash = "sha256-t98aQh96U9dHZKzOzcg/kQz9Cb4jD/aBSNvV+2IyIHs=";
  };

  src = if srcOverride != null then srcOverride else githubSrc;

  desktopItem = makeDesktopItem {
    name = "zap";
    exec = "zap %u";
    icon = "zap.github.vv01f";
    comment = "Zap LNAddress/LNURL 2 BOLT11 Invoice";
    desktopName = "Zap";
    genericName = "Lightning Zap";
    categories = [
      "Office"
      "Finance"
      "Utility"
    ];
    terminal = false;
    startupWMClass = "zap";
    keywords = [
      "bitcoin"
      "lightning"
      "payment"
      "ecash"
      "zap"
    ];
    mimeTypes = [
      "x-scheme-handler/lightning"
    ];
  };

  macAppAttrs = {
    name = "Zap";
    desktopName = "Zap";
    exec = "zap";
    icon = "zap.github.vv01f";
  };

in
buildPythonApplication rec {
  pname = "zap";
  version = "0.1.2";

  inherit src;

  pyproject = true;

  nativeBuildInputs = [
    setuptools
    wheel
    librsvg
  ]
  ++ lib.optionals (stdenv.hostPlatform.isDarwin && icnsutil != null) [
    icnsutil
  ];

  dependencies = [
    requests
    bech32
    pyside6
    qrcode
    pillow
    websocket-client
  ];

  postInstall =
    let
      plist = ''
        <?xml version="1.0" encoding="UTF-8"?>
        <!DOCTYPE plist PUBLIC "-//Apple Computer//DTD PLIST 1.0//EN"
        "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
        <plist version="1.0">
        <dict>
          <key>CFBundleName</key>
          <string>${macAppAttrs.name}</string>
          <key>CFBundleDisplayName</key>
          <string>${macAppAttrs.desktopName}</string>
          <key>CFBundleIdentifier</key>
          <string>com.vv01f.${macAppAttrs.name}</string>
          <key>CFBundleVersion</key>
          <string>${version}</string>
          <key>CFBundleExecutable</key>
          <string>${macAppAttrs.exec}</string>
          <key>CFBundleIconFile</key>
          <string>zap.icns</string>
          <key>LSUIElement</key>
          <false/>
          <key>CFBundlePackageType</key>
          <string>APPL</string>
        </dict>
        </plist>
      '';
    in
    ''
      ${lib.optionalString stdenv.hostPlatform.isLinux ''

          mkdir -p "$out/share/applications"

          install -Dm644 \
            ${desktopItem}/share/applications/* \
            "$out/share/applications/zap.desktop"

          install -Dm644 \
            ${src}/icons/zap.svg \
            "$out/share/icons/hicolor/scalable/apps/zap.github.vv01f.svg"

          for size in 16 32 48 64 128 256; do
            mkdir -p "$out/share/icons/hicolor/''${size}x''${size}/apps"

            rsvg-convert \
              -w "''${size}" \
              -h "''${size}" \
              ${src}/icons/zap.svg \
              -o "$out/share/icons/hicolor/''${size}x''${size}/apps/zap.github.vv01f.png"
          done

      ''}

      ${lib.optionalString stdenv.hostPlatform.isDarwin ''

          APPDIR="$out/Zap.app/Contents"
          mkdir -p "$APPDIR/MacOS"
          mkdir -p "$APPDIR/Resources"

          ICONSET="$TMPDIR/zap.iconset"
          mkdir -p "$ICONSET"

          for size in 16 32 128 256 512; do
            rsvg-convert \
              -w "$size" \
              -h "$size" \
              ${src}/icons/zap.svg \
              -o "$ICONSET/icon_''${size}x''${size}.png"

            double=$((size * 2))

            rsvg-convert \
              -w "$double" \
              -h "$double" \
              ${src}/icons/zap.svg \
              -o "$ICONSET/icon_''${size}x''${size}@2x.png"
          done

          icnsutil compose --force "$APPDIR/Resources/zap.icns" \
            "$ICONSET"/icon_*.png

          install -Dm755 \
            "$out/bin/zap" \
            "$APPDIR/MacOS/zap"

          cat > "$APPDIR/Info.plist" <<EOF
          ${plist}
          EOF
      ''}
    '';

  meta = {
    description = "Lightning Address / LNURL to BOLT11 invoice generator on CLI and PySide6 GUI.";

    longDescription = ''
      This GUI and CLI tool allows users to derive a BOLT11
      invoice from a Lightning Address or LNURL and desired
      parameters for a better UX with Lightning Payments.

      After installation, restart your desktop session so that
      the desktop entry and URI handler become visible.
    '';

    homepage = "https://github.com/vv01f/lightning-address-invoice-generator";
    changelog = null;
    license = lib.licenses.mit;
    mainProgram = "zap";

    platforms = lib.platforms.linux ++ lib.platforms.darwin;

    maintainers = [
      {
        name = "vv01f";
      }
    ];
  };
}
