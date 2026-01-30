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
