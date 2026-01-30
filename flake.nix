{
  description = "Zap – LNAddress to BOLT11 GUI";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs =
    {
      self,
      nixpkgs,
      flake-utils,
    }:
    flake-utils.lib.eachDefaultSystem (
      system:
      let
        pkgs = nixpkgs.legacyPackages.${system};
        zapPkg = pkgs.callPackage ./package.nix { };
      in
      {
        packages = {
          zap = zapPkg;
          default = zapPkg;
        };

        apps.zap = {
          type = "app";
          program = "${self.packages.${system}.zap}/bin/zap";
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
            license = pkgs.lib.licenses.mit;
            mainProgram = "zap";
            platforms = pkgs.lib.platforms.unix; # not tested: windows for lib.platforms.all
            maintainers = with pkgs.lib.maintainers; [ "vv01f" ];
          };
        };

        devShells.default = pkgs.mkShell {
          packages = with pkgs; [
            python3
            python3Packages.pyside6
            python3Packages.requests
            python3Packages.qrcode
            python3Packages.pillow
            python3Packages.bech32
          ];
        };
      }
    );
}
