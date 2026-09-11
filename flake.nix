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
        pkgs = import nixpkgs {
          inherit system;
          config.allowUnfree = true;
        };

        python = pkgs.python313;

        zapPkg = python.pkgs.callPackage ./package.nix { };
      in
      {
        packages = {
          zap = zapPkg;
          default = zapPkg;
        };

        apps = {
          format = {
            type = "app";
            program = "${pkgs.writeShellScript "zap-format" ''
              exec ${pkgs.ruff}/bin/ruff format .
            ''}";
          };

          zap = {
            type = "app";
            program = pkgs.lib.getExe zapPkg;
            meta = zapPkg.meta;
          };
        };

        devShells.default = pkgs.mkShell {
          inputsFrom = [
            zapPkg
          ];

          packages = [
            pkgs.ruff
            pkgs.nixfmt-rfc-style
          ];

          shellHook = ''
            echo "Zap development shell"
            echo "Python: $(python --version)"
          '';
        };
      }
    );
}
