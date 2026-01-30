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
      "crypto"
      "lightning"
      "zap"
    ];
  };
in
python3Packages.buildPythonApplication rec {
  pname = "zap";
  version = "0.1.0";

  src = ./.;

  pyproject = true;

  nativeBuildInputs = [
    python3Packages.setuptools
    python3Packages.wheel
  ];

  postInstall = ''
        ICON_FILE="$out/share/icons/hicolor/128x128/apps/zap.github.vv01f.png"
        if [ "$(uname -s)" = "Linux" ]; then
          mkdir -p $out/share/applications
          cp ${desktopItem}/share/applications/* $out/share/applications  
          # Desktop file
          #~ cat > $out/share/applications/zap.desktop <<EOF
    #~ [Desktop Entry]
    #~ Name=Zap
    #~ Comment=Lightning Address to BOLT11 invoice generator
    #~ Exec=${python3Packages.python}/bin/python3 ${placeholder "out"}/bin/zap
    #~ Icon=${placeholder "out"}/share/icons/hicolor/128x128/apps/zap.png
    #~ Type=Application
    #~ Categories=Finance;Utility;
    #~ Terminal=false
    #~ EOF
          # Example icon (replace with your actual icon if you have one)
          # taken from https://dashboardicons.com/icons/owasp-zap
          mkdir -p $out/share/icons/hicolor/128x128/apps
          #~ cp ./zap.png $out/share/icons/hicolor/128x128/apps/zap.png || true
          install -Dm644 "./zap.png" "$ICON_FILE"
        fi
  '';
  propagatedBuildInputs = [
    python3Packages.requests
    python3Packages.bech32
    python3Packages.pyside6
    python3Packages.qrcode
    python3Packages.pillow
  ];

  meta = {
    description = "Lightning Address to BOLT11 invoice generator on CLI with PySide6 GUI.";
    longDescription = ''
      This GUI and CLI Tool allows user to derive a BOLT11 Invoice from
      by passing a Lightning Address and desired parameters for a better
      UX with Lightning Payments.
    '';
    homepage = "https://github.com/vv01f/lightning-address-invoice-generator";
    license = lib.licenses.mit;
    mainProgram = "zap";
    platforms = [
      "x86_64-linux"
      "aarch64-linux"
      "x86_64-darwin"
      "aarch64-darwin"
    ];
    maintainers = with lib.maintainers; [ "vv01f" ];
  };
}
