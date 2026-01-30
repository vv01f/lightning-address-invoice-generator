{
  lib,
  python3,
  python3Packages,
  makeDesktopItem,
}:

let
  desktopItem = makeDesktopItem {
    name = "Zap";
    exec = "zap";
    icon = "zap.github.vv01f";
    comment = "Zap LNAddress 2 BOLT11 Invoice";
    desktopName = "Zap";
    categories = [
      "Office"
      "Finance"
      "Utility"
    ];
    terminal = false;
    startupWMClass = "Zap";
    keywords = [
      "bitcoin"
      "lightning"
      "payment"
      "ecash"
      "zap"
    ];
  };

  macAppAttrs = {
    name = "Zap";
    desktopName = "Zap";
    exec = "zap";
    icon = "zap.github.vv01f";
  };
in
python3Packages.buildPythonApplication rec {
  pname = "zap";
  version = "0.1.0";

  src = ./.;

  pyproject = true;

  nativeBuildInputs = with python3Packages; [
    setuptools
    wheel
  ];

  postInstall = let
    plist = ''
      <?xml version="1.0" encoding="UTF-8"?>
      <!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" 
      "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
      <plist version="1.0">
      <dict>
        <key>CFBundleName</key><string>${macAppAttrs.name}</string>
        <key>CFBundleDisplayName</key><string>${macAppAttrs.desktopName}</string>
        <key>CFBundleIdentifier</key><string>com.vv01f.${macAppAttrs.name}</string>
        <key>CFBundleVersion</key><string>0.1.0</string>
        <key>CFBundleExecutable</key><string>${macAppAttrs.exec}</string>
        <key>CFBundleIconFile</key><string>${macAppAttrs.icon}.png</string>
        <key>LSUIElement</key><false/>
        <key>CFBundlePackageType</key><string>APPL</string>
      </dict>
      </plist>
    '';
  in ''
    case "$(uname -s)" in
      Linux)
        mkdir -p $out/share/applications
        mkdir -p $out/share/icons/hicolor/128x128/apps
        install -Dm644 ${desktopItem}/share/applications/* $out/share/applications
        install -Dm644 "./zap.png" "$out/share/icons/hicolor/128x128/apps/zap.github.vv01f.png"
        ;;
      Darwin)
        APPDIR="$out/Zap.app/Contents"
        mkdir -p $APPDIR/{MacOS,Resources}
        install -Dm644 ./zap.png $APPDIR/Resources/zap.png
        install -Dm755 ./zap.py $APPDIR/MacOS/zap
        echo "${plist}" > $APPDIR/Info.plist
        #~ cat > $APPDIR/Info.plist <<EOF
#~ EOF
        ;;
      *) echo "Unsupported platform: $(uname -s)" ;;
    esac
  '';

  propagatedBuildInputs = with python3Packages; [
    requests
    bech32
    pyside6
    qrcode
    pillow
  ];

  meta = {
    description = "Lightning Address to BOLT11 invoice generator on CLI with PySide6 GUI.";
    longDescription = ''
      This GUI and CLI Tool allows user to derive a BOLT11 Invoice from
      by passing a Lightning Address and desired parameters for a better
      UX with Lightning Payments.
    '';
    homepage = "https://github.com/vv01f/lightning-address-invoice-generator";
    source = "https://github.com/vv01f/lightning-address-invoice-generator.git";
    bugReports = "https://github.com/vv01f/lightning-address-invoice-generator/issues";
    license = lib.licenses.mit;
    mainProgram = "zap";
    platforms = lib.platforms.unix; # not tested: windows for lib.platforms.all
    maintainers = with lib.maintainers; [ "vv01f" ];
  };
}
