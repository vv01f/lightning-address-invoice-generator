with import <nixpkgs> { };

(python3.withPackages (
  ps: with ps; [
    requests
    bech32 # maybe bech32-py or python-bech32
    pyside6
  ]
)).env
